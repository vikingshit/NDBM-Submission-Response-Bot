import os
import discord
import base64
import logging
from discord.ext import commands, tasks
from dotenv import load_dotenv
from playlists import VALIDATION_EMOJI, REJECTION_EMOJI, PLAYLIST_CONFIG
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from email.mime.text import MIMEText
from googleapiclient.discovery import build

# Configuration du logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Charger les variables d'environnement
load_dotenv()

# Configuration Discord
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = int(os.getenv('GUILD_ID'))

# Configuration des intents Discord
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True
intents.typing = False
intents.messages = True

# Créer l'instance du bot
bot = commands.Bot(command_prefix='!', intents=intents)

# Configuration Google Sheets
SHEET_ID = os.getenv('SHEET_ID')
SHEET_NAME = os.getenv('SHEET_NAME')
CREDS_FILE = os.getenv('CREDS_FILE')
GMAIL_CREDS_FILE = os.getenv('GMAIL_CREDS_FILE')
SENDER_EMAIL = os.getenv('SENDER_EMAIL')

scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

# Configuration Gmail
gmail_creds = ServiceAccountCredentials.from_json_keyfile_name(GMAIL_CREDS_FILE, ['https://www.googleapis.com/auth/gmail.send'])
gmail_service = build('gmail', 'v1', credentials=gmail_creds)

# Variable pour suivre la dernière ligne traitée
last_processed_row = 1

@tasks.loop(minutes=5)  # Vérifie toutes les 5 minutes au lieu de 24 heures
async def check_submissions():
    try:
        # Récupérer toutes les soumissions du Google Sheet
        all_submissions = sheet.get_all_records(default_blank=None)
        
        if not all_submissions:
            logger.info("Aucune soumission trouvée")
            return
            
        # Log du nombre total de soumissions
        logger.info(f"Nombre total de soumissions: {len(all_submissions)}")
        
        # Ne prendre que la dernière soumission
        latest_submission = all_submissions[-1]
        logger.info(f"Dernière soumission trouvée: {latest_submission}")
        
        # Vérifier si la soumission a déjà été traitée
        if latest_submission.get('Statut 📩❌✅'):
            logger.info("La dernière soumission a déjà été traitée")
            return
            
        # Traiter la dernière soumission
        await process_submission(latest_submission)
        
        # Marquer la soumission comme traitée
        last_row = len(all_submissions) + 1  # +1 car les en-têtes sont dans la première ligne
        sheet.update_cell(last_row, 12, '📩')  # 12 est la colonne "Statut"
        logger.info("Statut mis à jour pour la dernière soumission")
        
    except Exception as e:
        logger.error(f"Erreur lors de la vérification des soumissions : {e}")

@bot.event
async def on_ready():
    logger.info(f'Bot connecté en tant que {bot.user}')
    check_submissions.start()
    logger.info("Tâche de vérification des soumissions démarrée")

async def process_submission(submission):
    logger.info(f"Traitement de la soumission : {submission}")
    
    try:
        # Séparer le nom de l'artiste et le nom de la track
        artist_track = submission['Artist Name - Track Name (mandatory)']
        if artist_track:
            # Séparation par le tiret pour obtenir artiste et track
            parts = artist_track.split('-')
            artist_name = parts[0].strip()
            track_name = '-'.join(parts[1:]).strip()  # Pour gérer les tracks avec des tirets
        else:
            logger.warning("Pas de nom d'artiste/track")
            return

        email = submission['Adresse e-mail']
        if not email:
            logger.warning("Pas d'email")
            return

        submitted_playlist = submission['For which one of our playlists are you submitting a track?']
        if not submitted_playlist:
            logger.warning("Pas de playlist sélectionnée")
            return

        # Utiliser le mapping pour trouver la bonne clé de playlist
        playlist_key = PLAYLIST_MAPPING.get(submitted_playlist.upper())
        if not playlist_key:
            logger.warning(f"Pas de mapping trouvé pour la playlist : {submitted_playlist}")
            return

        logger.info(f"Informations extraites : Artiste={artist_name}, Track={track_name}, Email={email}, Playlist={playlist_key}")

        # Utiliser la clé mappée pour trouver la configuration de la playlist
        playlist = PLAYLIST_CONFIG.get(playlist_key)
        if playlist:
            channel_id = playlist['channel_id']
            channel = bot.get_channel(int(channel_id))
            if channel:
                message = f"Nouvelle soumission pour la playlist {playlist['name']} de {artist_name} - {track_name} (Email: {email})"
                try:
                    message_sent = await channel.send(message)
                    await message_sent.add_reaction(VALIDATION_EMOJI)
                    await message_sent.add_reaction(REJECTION_EMOJI)
                    logger.info(f"Message envoyé avec succès pour {artist_name}")
                    
                    # Envoyer un e-mail de notification
                    subject = "Nouvelle soumission de track"
                    body = f"Une nouvelle track a été soumise par {artist_name} pour la playlist {playlist['name']}."
                    await send_email(email, subject, body)
                except Exception as e:
                    logger.error(f"Erreur lors de l'envoi du message : {e}")
            else:
                logger.error(f"Canal introuvable pour l'ID : {channel_id}")
        else:
            logger.warning(f"Configuration introuvable pour la playlist : {playlist_key}")
            
    except Exception as e:
        logger.error(f"Erreur lors du traitement de la soumission : {e}")

async def send_email(to, subject, body):
    try:
        # Créer le message e-mail
        message = MIMEText(body)
        message['to'] = to
        message['subject'] = subject
        
        # Envoyer l'e-mail via l'API Gmail
        create_message = {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}
        send_message = (gmail_service.users().messages().send(userId="me", body=create_message).execute())
        logger.info(f"Email envoyé avec succès à {to}")
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi de l'email : {e}")

@bot.event
async def on_raw_reaction_add(payload):
    try:
        if payload.emoji.name == VALIDATION_EMOJI:
            channel = bot.get_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)
            content = message.content
            playlist_name = content.split(' ')[-5]  # Extraire le nom de la playlist du message
            email = content.split('(Email: ')[1].split(')')[0]
            playlist = PLAYLIST_CONFIG.get(playlist_name.lower())
            
            if playlist:
                subject = f"Votre track a été acceptée dans la playlist {playlist['name']}"
                body = f"Félicitations ! Votre track a été acceptée dans la playlist {playlist['name']} (ID Spotify: {playlist['spotify_playlist_id']})."
                await send_email(email, subject, body)
                logger.info(f"Email d'acceptation envoyé pour la playlist {playlist['name']}")
            else:
                logger.warning(f"Playlist inconnue : {playlist_name}")
        
        elif payload.emoji.name == REJECTION_EMOJI:
            channel = bot.get_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)
            content = message.content
            email = content.split('(Email: ')[1].split(')')[0]
            
            subject = "Votre track n'a pas été retenue"
            body = "Désolé, votre track n'a pas été retenue cette fois-ci."
            await send_email(email, subject, body)
            logger.info("Email de rejet envoyé")
    except Exception as e:
        logger.error(f"Erreur lors du traitement de la réaction : {e}")

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
