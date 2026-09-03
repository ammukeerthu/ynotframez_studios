(function () {
  async function apiRequest(url, options = {}) {
    const response = await fetch(url, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = Array.isArray(payload.detail)
        ? payload.detail.map((item) => item.msg).filter(Boolean).join(" ")
        : payload.detail;
      throw new Error(detail || "The payment could not be verified.");
    }
    return payload;
  }

  function open(booking, callbacks = {}) {
    if (!booking?.checkout?.key_id || !booking.checkout.order_id) {
      callbacks.onError?.("Online checkout is temporarily unavailable. Please try again shortly.");
      return;
    }
    if (typeof window.Razorpay !== "function") {
      callbacks.onError?.("Razorpay Checkout could not be loaded. Check your connection and try again.");
      return;
    }

    let verified = false;
    let submitted = false;
    const checkout = new window.Razorpay({
      key: booking.checkout.key_id,
      amount: booking.checkout.amount,
      currency: booking.checkout.currency,
      order_id: booking.checkout.order_id,
      name: "YNotFramez Studios",
      description: `${booking.space_name} booking ${booking.reference}`,
      prefill: {
        name: booking.customer_name,
        email: booking.customer_email,
        contact: booking.phone_number || "",
      },
      notes: { booking_reference: booking.reference },
      theme: { color: "#ff5b35" },
      retry: { enabled: true },
      modal: {
        confirm_close: true,
        ondismiss: () => {
          if (!verified && !submitted) callbacks.onDismiss?.();
        },
      },
      handler: async (response) => {
        submitted = true;
        callbacks.onVerifying?.();
        try {
          const updated = await apiRequest("/api/payments/razorpay/verify", {
            method: "POST",
            body: JSON.stringify({
              reference: booking.reference,
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_order_id: response.razorpay_order_id,
              razorpay_signature: response.razorpay_signature,
            }),
          });
          verified = true;
          if (updated.status === "confirmed") callbacks.onVerified?.(updated);
          else callbacks.onProcessing?.(updated);
        } catch (error) {
          if (callbacks.onVerificationError) callbacks.onVerificationError(error.message);
          else callbacks.onError?.(error.message);
        }
      },
    });

    checkout.on("payment.failed", (response) => {
      const description = response?.error?.description || "The payment attempt failed. You can retry safely.";
      callbacks.onFailure?.(description);
    });
    checkout.open();
  }

  window.YNFPayments = { open };
})();
