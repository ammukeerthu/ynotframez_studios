import hashlib
import hmac
import unittest
from unittest.mock import MagicMock, patch

from app.core.config import settings
from app.models.booking import Booking
from app.services.razorpay_service import RazorpayService


class RazorpayServiceTest(unittest.TestCase):
    def booking(self) -> Booking:
        return Booking(
            id=42,
            phone_number="+919999999999",
            space_id="standard_small",
            duration_hours=2,
            customer_name="Razorpay Customer",
            customer_email="customer@example.com",
        )

    def test_api_mode_creates_real_payment_link_request_in_paise(self) -> None:
        response = MagicMock()
        response.json.return_value = {"id": "plink_test_42", "short_url": "https://rzp.io/i/test42"}
        with (
            patch.object(settings, "razorpay_mode", "api"),
            patch.object(settings, "razorpay_key_id", "rzp_test_key"),
            patch.object(settings, "razorpay_key_secret", "test_secret"),
            patch.object(settings, "razorpay_callback_base_url", "https://studio.example"),
            patch("app.services.razorpay_service.requests.post", return_value=response) as post,
        ):
            link = RazorpayService().create_payment_link(self.booking())

        self.assertEqual(link.id, "plink_test_42")
        self.assertEqual(link.url, "https://rzp.io/i/test42")
        request = post.call_args.kwargs
        self.assertEqual(request["auth"], ("rzp_test_key", "test_secret"))
        self.assertEqual(request["json"]["amount"], 240000)
        self.assertEqual(request["json"]["currency"], "INR")
        self.assertEqual(request["json"]["reference_id"], "YNF-000042")
        self.assertIn("/payment/return/YNF-000042", request["json"]["callback_url"])

    def test_webhook_signature_uses_raw_body_hmac_sha256(self) -> None:
        body = b'{"event":"payment_link.paid"}'
        with patch.object(settings, "razorpay_webhook_secret", "webhook-secret"):
            signature = hmac.new(b"webhook-secret", body, hashlib.sha256).hexdigest()
            self.assertTrue(RazorpayService.verify_webhook_signature(body, signature))
            self.assertFalse(RazorpayService.verify_webhook_signature(body, "invalid"))


if __name__ == "__main__":
    unittest.main()
