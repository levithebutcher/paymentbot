import asyncio
import os
import unittest
import uuid
from config import config

class TestPaymentBotDatabase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db_name = f"test_{uuid.uuid4().hex[:8]}.db"
        config.DB_PATH = self.db_name
        
        import database
        self.db = database
        await self.db.init_db()

    async def asyncTearDown(self):
        await asyncio.sleep(0.05)
        if os.path.exists(self.db_name):
            try:
                os.remove(self.db_name)
            except OSError:
                pass

    async def test_services_seeded(self):
        services = await self.db.get_services()
        self.assertGreaterEqual(len(services), 1)
        vip = await self.db.get_service("vip_access")
        self.assertIsNotNone(vip)
        self.assertEqual(vip["price_inr"], 199.0)

    async def test_user_upsert(self):
        await self.db.upsert_user(1234567, "testuser", "Test User")
        orders = await self.db.get_user_orders(1234567)
        self.assertEqual(len(orders), 0)

    async def test_order_creation_and_fraud_protection(self):
        user_id = 998877
        await self.db.upsert_user(user_id, "buyer", "Buyer Name")
        
        order_id_1 = "ORD-TEST01"
        await self.db.create_order(order_id_1, user_id, "vip_access", 199.0)
        
        order = await self.db.get_order(order_id_1)
        self.assertIsNotNone(order)
        self.assertEqual(order["status"], "PENDING_PAYMENT")

        # First user submits proof with UTR 123456789012
        utr_1 = "123456789012"
        self.assertFalse(await self.db.check_utr_exists(utr_1))
        
        success = await self.db.submit_order_proof(order_id_1, "file_photo_1", utr=utr_1)
        self.assertTrue(success)
        
        # Now UTR must be marked as existing
        self.assertTrue(await self.db.check_utr_exists(utr_1))

        # Attacker tries to submit same UTR on a different order
        order_id_2 = "ORD-TEST02"
        await self.db.upsert_user(888888, "attacker", "Attacker")
        await self.db.create_order(order_id_2, 888888, "vip_access", 199.0)
        
        # check_utr_exists must catch this immediately
        self.assertTrue(await self.db.check_utr_exists(utr_1))

    async def test_admin_approve_flow(self):
        user_id = 112233
        await self.db.upsert_user(user_id, "buyer2", "Buyer 2")
        order_id = "ORD-APPROVE"
        await self.db.create_order(order_id, user_id, "vip_access", 199.0)
        await self.db.submit_order_proof(order_id, "screenshot_123", utr="987654321098")

        # Admin approves
        admin_id = 55555
        approved_order = await self.db.approve_order(order_id, admin_id)
        self.assertIsNotNone(approved_order)
        self.assertEqual(approved_order["status"], "COMPLETED")
        self.assertEqual(approved_order["admin_id"], admin_id)
        self.assertIn("https://t.me/+SampleVIPInviteLink123", approved_order["delivery_content"])

    async def test_admin_reject_flow(self):
        user_id = 445566
        await self.db.upsert_user(user_id, "buyer3", "Buyer 3")
        order_id = "ORD-REJECT"
        await self.db.create_order(order_id, user_id, "vip_access", 199.0)
        await self.db.submit_order_proof(order_id, "screenshot_fake", utr="555555555555")

        # Admin rejects
        admin_id = 55555
        reason = "Payment not credited to bank account"
        rejected_order = await self.db.reject_order(order_id, admin_id, reason)
        self.assertIsNotNone(rejected_order)
        self.assertEqual(rejected_order["status"], "REJECTED")
        self.assertEqual(rejected_order["rejection_reason"], reason)

    async def test_service_management_crud(self):
        svc_id = "new_course_2026"
        # 1. Add service
        added = await self.db.add_service(
            service_id=svc_id,
            title="Python Masterclass",
            description="Complete AI & Python course",
            price_inr=499.0,
            delivery_content="https://drive.google.com/test_course"
        )
        self.assertTrue(added)

        svc = await self.db.get_service(svc_id)
        self.assertIsNotNone(svc)
        self.assertEqual(svc["price_inr"], 499.0)

        # 2. Update price
        updated_price = await self.db.update_service_price(svc_id, 299.0)
        self.assertTrue(updated_price)
        svc = await self.db.get_service(svc_id)
        self.assertEqual(svc["price_inr"], 299.0)

        # 3. Update delivery
        updated_del = await self.db.update_service_delivery(svc_id, "https://t.me/+new_invite")
        self.assertTrue(updated_del)
        svc = await self.db.get_service(svc_id)
        self.assertEqual(svc["delivery_content"], "https://t.me/+new_invite")

        # 4. Update title
        updated_title = await self.db.update_service_title(svc_id, "Python Pro 2026")
        self.assertTrue(updated_title)
        svc = await self.db.get_service(svc_id)
        self.assertEqual(svc["title"], "Python Pro 2026")

        # 5. Toggle status (Active -> Inactive)
        new_status = await self.db.toggle_service_status(svc_id)
        self.assertEqual(new_status, 0)
        # Should not appear in active-only services
        active_svcs = await self.db.get_services(active_only=True)
        self.assertNotIn(svc_id, [s["service_id"] for s in active_svcs])

        # Toggle back to Active
        new_status = await self.db.toggle_service_status(svc_id)
        self.assertEqual(new_status, 1)

        # 6. Delete service
        deleted = await self.db.delete_service(svc_id)
        self.assertTrue(deleted)
        self.assertIsNone(await self.db.get_service(svc_id))

    async def test_get_all_users_for_broadcast(self):
        await self.db.upsert_user(1001, "u1", "User One")
        await self.db.upsert_user(1002, "u2", "User Two")
        await self.db.upsert_user(1003, "u3", "User Three")

        all_users = await self.db.get_all_users()
        self.assertIn(1001, all_users)
        self.assertIn(1002, all_users)
        self.assertIn(1003, all_users)
        self.assertGreaterEqual(len(all_users), 3)

    async def test_settings_get_set(self):
        # Default seeded value
        upi = await self.db.get_setting("upi_id")
        self.assertEqual(upi, config.UPI_ID)

        # Update setting
        await self.db.set_setting("upi_id", "newtest@upi")
        updated = await self.db.get_setting("upi_id")
        self.assertEqual(updated, "newtest@upi")

        # Fallback default
        val = await self.db.get_setting("non_existent_key", default="fallback")
        self.assertEqual(val, "fallback")

    async def test_order_message_mapping(self):
        user_id = 991122
        await self.db.upsert_user(user_id, "replybuyer", "Reply Buyer")
        order_id = "ORD-REPLY01"
        await self.db.create_order(order_id, user_id, "vip_access", 199.0)
        await self.db.submit_order_proof(order_id, "photo_xyz")

        # Map admin card message
        admin_msg_id = 8844
        admin_chat_id = -100123456
        await self.db.save_admin_order_message(admin_msg_id, admin_chat_id, order_id)

        # Retrieve order
        matched_order = await self.db.get_order_by_message(admin_msg_id, admin_chat_id)
        self.assertIsNotNone(matched_order)
        self.assertEqual(matched_order["order_id"], order_id)
        self.assertEqual(matched_order["user_id"], user_id)

if __name__ == "__main__":
    unittest.main()
