import unittest
from unittest.mock import Mock, patch, AsyncMock
import os
from dotenv import load_dotenv
import asyncio
import sys
import json
import base64
from email.mime.text import MIMEText

# Mock les modules avant d'importer le bot
sys.modules['discord'] = Mock()
sys.modules['discord.ext'] = Mock()
sys.modules['discord.ext.commands'] = Mock()
sys.modules['discord.ext.tasks'] = Mock()
sys.modules['gspread'] = Mock()
sys.modules['oauth2client.service_account'] = Mock()
sys.modules['googleapiclient.discovery'] = Mock()

# Configuration de test pour les playlists
PLAYLIST_CONFIG = {
    'playlist1': {
        'name': 'Test Playlist',
        'channel_id': '123456789',
        'spotify_playlist_id': 'test_id'
    }
}

# Create a mock playlists module
mock_playlists = Mock()
mock_playlists.PLAYLIST_CONFIG = PLAYLIST_CONFIG
mock_playlists.VALIDATION_EMOJI = '✅'
mock_playlists.REJECTION_EMOJI = '❌'
sys.modules['playlists'] = mock_playlists

# Mock le service account credentials
mock_credentials = Mock()
sys.modules['oauth2client.service_account'].ServiceAccountCredentials = Mock()
sys.modules['oauth2client.service_account'].ServiceAccountCredentials.from_json_keyfile_name = Mock(return_value=mock_credentials)

# Mock le client gspread
mock_worksheet = Mock()
mock_worksheet.col_values = Mock(return_value=['header', 'row1'])
mock_worksheet.get_all_records = Mock(return_value=[{'col1': 'val1'}])

mock_spreadsheet = Mock()
mock_spreadsheet.worksheet = Mock(return_value=mock_worksheet)

mock_gspread_client = Mock()
mock_gspread_client.open_by_key = Mock(return_value=mock_spreadsheet)

sys.modules['gspread'].authorize = Mock(return_value=mock_gspread_client)

# Charger les variables d'environnement de test
load_dotenv('.env.test')

# Import le bot après tous les mocks
from bot import process_submission, send_email, bot

class TestDiscordBot(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.test_submission = {
            'Artist Name': 'Test Artist',
            'Track Name': 'Test Track',
            'Email': 'test@example.com',
            'For which one of our playlists are you submitting a track?': 'playlist1'
        }
        
        # Mock Discord channel
        self.mock_channel = AsyncMock()
        self.mock_message = AsyncMock()
        self.mock_message.add_reaction = AsyncMock()
        self.mock_channel.send = AsyncMock(return_value=self.mock_message)
        
        # Mock bot
        self.mock_bot = Mock()
        self.mock_bot.get_channel = Mock(return_value=self.mock_channel)

    @patch('bot.bot')
    @patch('bot.send_email')
    async def test_process_submission(self, mock_send_email, mock_bot):
        print("\nTesting process_submission...")
        mock_bot.get_channel = self.mock_bot.get_channel
        
        try:
            await process_submission(self.test_submission)
            print("✓ Process submission completed successfully")
        except Exception as e:
            print(f"✗ Process submission failed: {str(e)}")
            raise
        
        self.mock_channel.send.assert_called_once()
        print("✓ Discord message was sent")
        
        mock_send_email.assert_called_once()
        print("✓ Email notification was triggered")
        
        call_args = self.mock_channel.send.call_args
        self.assertIn('Test Artist', call_args[0][0])
        self.assertIn('Test Track', call_args[0][0])
        print("✓ Message content was correct")

    @patch('bot.gmail_service')
    async def test_send_email(self, mock_gmail_service):
        print("\nTesting send_email...")
        mock_messages = Mock()
        mock_gmail_service.users().messages.return_value = mock_messages
        mock_messages.send = Mock(return_value=Mock(execute=Mock(return_value={})))
        
        test_to = 'test@example.com'
        test_subject = 'Test Subject'
        test_body = 'Test Body'
        
        try:
            await send_email(test_to, test_subject, test_body)
            print("✓ Email send completed successfully")
        except Exception as e:
            print(f"✗ Email send failed: {str(e)}")
            raise
        
        mock_messages.send.assert_called_once()
        print("✓ Gmail API was called")
        
        call_args = mock_messages.send.call_args
        self.assertIn('userId', call_args[1])
        self.assertEqual(call_args[1]['userId'], 'me')
        print("✓ Email parameters were correct")

if __name__ == '__main__':
    unittest.main(verbosity=2)