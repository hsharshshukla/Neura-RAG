// src/pages/RefundPolicy.jsx
import React from "react";

export default function RefundPolicy() {
  return (
    <div className="max-w-3xl mx-auto p-6 prose">
      <h1>Refund Policy — Neura</h1>
      <p>
        <strong>Effective:</strong> August 12, 2025 &nbsp; | &nbsp;{" "}
        <strong>Version:</strong> 1.0
      </p>

      <p>
        This Refund Policy explains when customers may be eligible for a refund
        for purchases of Neura subscriptions made through our payment provider,
        Paddle.
      </p>

      <h2>1. Payments via Paddle</h2>
      <p>
        Neura uses Paddle as its Merchant of Record. All payments for Neura are
        processed by Paddle, and your card statement may reflect Paddle or one of
        its payment partners. By purchasing a subscription, you agree to abide by
        this Refund Policy and any applicable Paddle terms.
      </p>

      <h2>2. General Rule</h2>
      <p>
        As a default, all fees for Neura subscriptions and usage are{" "}
        <strong>non-refundable</strong>, except where required by applicable law
        or as expressly allowed under this Refund Policy. We encourage you to
        evaluate the Service using any free tier, free trial, or demo options
        before upgrading to a paid plan.
      </p>

      <h2>3. Situations Where We May Provide a Refund</h2>
      <p>
        At our discretion, and subject to Paddle&apos;s processes, we may approve
        a full or partial refund in the following situations:
      </p>
      <ul>
        <li>
          <strong>Duplicate payment:</strong> you were charged twice for the same
          subscription period.
        </li>
        <li>
          <strong>Technical issues on our side:</strong> a prolonged, verified
          outage or defect prevented you from using the Service in a material way
          and we were unable to resolve it within a reasonable time after you
          reported it.
        </li>
        <li>
          <strong>Unauthorized payment:</strong> your payment method was used
          without your authorization, and you notify us and your payment provider
          promptly.
        </li>
        <li>
          <strong>Legal requirements:</strong> a refund is required under
          applicable consumer protection laws in your jurisdiction.
        </li>
      </ul>

      <h2>4. Subscription Renewals</h2>
      <p>
        Subscriptions renew automatically at the end of each billing period
        unless you cancel before the renewal date. If you cancel after a renewal
        has already been processed, your subscription will remain active until
        the end of the current billing period, and{" "}
        <strong>no pro-rata refunds</strong> will be issued for the remaining
        time in that period, unless required by law.
      </p>

      <h2>5. How to Request a Refund</h2>
      <p>
        To request a refund, please contact us at{" "}
        <a href="mailto:alpha@neurokron.com">support@neura.com</a> and include:
      </p>
      <ul>
        <li>The email address associated with your Neura account.</li>
        <li>The Paddle receipt or order ID.</li>
        <li>The date and amount of the charge.</li>
        <li>
          A brief description of the issue and the reason you are requesting a
          refund.
        </li>
      </ul>
      <p>
        In some cases, Paddle may handle the refund directly. We may direct you
        to Paddle&apos;s support team to complete the refund process in line with
        their policies.
      </p>

      <h2>6. Timing of Refunds</h2>
      <p>
        If a refund is approved, processing times may vary depending on your bank
        or card issuer. Typically, it may take up to 7–10 business days for the
        refunded amount to appear in your account after Paddle has processed it.
      </p>

      <h2>7. Chargebacks</h2>
      <p>
        Before initiating a chargeback with your bank or card issuer, we
        encourage you to contact us and give us the opportunity to resolve the
        issue. Unresolved or repeated chargebacks may lead to suspension or
        termination of your Neura account.
      </p>

      <h2>8. Changes to This Refund Policy</h2>
      <p>
        We may update this Refund Policy from time to time. If we make material
        changes, we will take reasonable steps to notify you. Your continued use
        of the Service after the updated policy becomes effective constitutes
        your acceptance of the changes.
      </p>

      <h2>Contact</h2>
      <p>
        For questions about this Refund Policy, contact us at{" "}
        <a href="mailto:alpha@neurokron.com">support@neura.com</a>.
      </p>

      <footer className="text-sm text-gray-500 mt-8">
        Legal Version: <strong>2025-08-20</strong>
      </footer>
    </div>
  );
}
