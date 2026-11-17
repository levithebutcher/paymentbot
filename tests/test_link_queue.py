import unittest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from link_queue import LinkResolverQueue, ResolveTask
from handlers.start import extract_resolvable_urls, extract_resolvable_urls_and_context
from aiogram.types import MessageEntity

class TestLinkQueue(unittest.TestCase):
    def test_extract_pastelink_url(self):
        msg = MagicMock()
        msg.text = "Here is the paste: https://pastelink.net/8k0t0va3"
        msg.caption = None
        msg.entities = None
        msg.caption_entities = None
        urls = extract_resolvable_urls(msg)
        self.assertEqual(urls, ["https://pastelink.net/8k0t0va3"])

    def test_extract_pslk_shortlink(self):
        msg = MagicMock()
        msg.text = "Alternative shortlink: https://pslk.net/8k0t0va3"
        msg.caption = None
        msg.entities = None
        msg.caption_entities = None
        urls = extract_resolvable_urls(msg)
        self.assertEqual(urls, ["https://pslk.net/8k0t0va3"])

    def test_extract_from_plain_text(self):
        msg = MagicMock()
        msg.text = "Check this: https://s3.eu-central-1.amazonaws.com/pastes/123.txt"
        msg.caption = None
        msg.entities = None
        msg.caption_entities = None
        urls = extract_resolvable_urls(msg)
        self.assertEqual(urls, ["https://s3.eu-central-1.amazonaws.com/pastes/123.txt"])

    def test_extract_with_trailing_punctuation(self):
        msg = MagicMock()
        msg.text = "Here is the paste: (https://s3.eu-central-1.amazonaws.com/pastes/123.txt)."
        msg.caption = None
        msg.entities = None
        msg.caption_entities = None
        urls = extract_resolvable_urls(msg)
        self.assertEqual(urls, ["https://s3.eu-central-1.amazonaws.com/pastes/123.txt"])

    def test_extract_accompanying_context(self):
        msg = MagicMock()
        msg.text = "🌟 PUBG Mobile Hack 🌟\nKey: VIP-999\nhttps://s3.eu-central-1.amazonaws.com/pastes/123.txt\nEnjoy!"
        msg.caption = None
        msg.entities = None
        msg.caption_entities = None
        urls, context = extract_resolvable_urls_and_context(msg)
        self.assertEqual(urls, ["https://s3.eu-central-1.amazonaws.com/pastes/123.txt"])
        self.assertIn("🌟 PUBG Mobile Hack 🌟", context)
        self.assertIn("Key: VIP-999", context)
        self.assertNotIn("https://s3.eu-central-1.amazonaws.com", context)

    def test_extract_from_forwarded_caption(self):
        # When a forwarded message has a photo or document
        msg = MagicMock()
        msg.text = None
        msg.caption = "Forwarded post: https://linkvertise.com/12345/abc"
        msg.entities = None
        msg.caption_entities = None
        urls = extract_resolvable_urls(msg)
        self.assertEqual(urls, ["https://linkvertise.com/12345/abc"])

    def test_extract_from_text_link_entity(self):
        # When a forwarded message has a hyperlink "[Click here](https://s3...)"
        msg = MagicMock()
        msg.text = "Click Here to Download"
        msg.caption = None
        entity = MagicMock(spec=MessageEntity)
        entity.type = "text_link"
        entity.url = "https://s3.amazonaws.com/bucket/file.txt"
        msg.entities = [entity]
        msg.caption_entities = None
        urls = extract_resolvable_urls(msg)
        self.assertEqual(urls, ["https://s3.amazonaws.com/bucket/file.txt"])

    def test_queue_initialization(self):
        queue = LinkResolverQueue(concurrency=2)
        self.assertEqual(queue._concurrency, 2)
        self.assertEqual(queue._queue.qsize(), 0)

    def test_queue_processing(self):
        async def run_test():
            queue = LinkResolverQueue(concurrency=1)
            
            mock_msg = MagicMock()
            mock_msg.answer = AsyncMock()
            mock_msg.delete = AsyncMock()

            mock_status = MagicMock()
            mock_status.edit_text = AsyncMock()
            mock_msg.answer.return_value = mock_status

            with patch("link_queue.extract_final_link_async", new_callable=AsyncMock) as mock_extract:
                mock_extract.return_value = "https://t.me/ResolvedChannel"
                
                await queue.enqueue(mock_msg, "https://s3.amazonaws.com/test.txt")
                
                # Allow worker to process the task
                await asyncio.sleep(0.6)

                mock_extract.assert_called_once_with("https://s3.amazonaws.com/test.txt")
                mock_status.edit_text.assert_called()
                mock_msg.delete.assert_called_once()

                # Clean up workers
                for w in queue._workers:
                    w.cancel()

        asyncio.run(run_test())

    def test_queue_processing_with_context(self):
        async def run_test():
            queue = LinkResolverQueue(concurrency=1)
            
            mock_msg = MagicMock()
            mock_msg.answer = AsyncMock()
            mock_msg.delete = AsyncMock()

            mock_status = MagicMock()
            mock_status.edit_text = AsyncMock()
            mock_msg.answer.return_value = mock_status

            with patch("link_queue.extract_final_link_async", new_callable=AsyncMock) as mock_extract:
                mock_extract.return_value = "https://t.me/ResolvedChannel"
                
                await queue.enqueue(
                    mock_msg,
                    "https://s3.amazonaws.com/test.txt",
                    context_text="Key: VIP123\nVersion 2.0"
                )
                
                # Allow worker to process the task
                await asyncio.sleep(0.6)

                mock_extract.assert_called_once_with("https://s3.amazonaws.com/test.txt")
                self.assertTrue(mock_status.edit_text.called)
                args, kwargs = mock_status.edit_text.call_args
                reply_body = args[0] if args else kwargs.get("text", "")
                self.assertIn("Key: VIP123", reply_body)
                self.assertIn("Version 2.0", reply_body)
                self.assertIn("https://t.me/ResolvedChannel", reply_body)
                mock_msg.delete.assert_called_once()

                for w in queue._workers:
                    w.cancel()

        asyncio.run(run_test())

if __name__ == "__main__":
    unittest.main()
