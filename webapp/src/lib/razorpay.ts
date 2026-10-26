// Razorpay Checkout loader + promise wrapper. Checkout is a hosted script (it can't be
// bundled), so it's injected on first use rather than slowing every page load.

declare global {
  interface Window { Razorpay?: any; }
}

let loader: Promise<void> | null = null;

function loadCheckoutScript(): Promise<void> {
  if (window.Razorpay) return Promise.resolve();
  if (!loader) {
    loader = new Promise<void>((resolve, reject) => {
      const el = document.createElement('script');
      el.src = 'https://checkout.razorpay.com/v1/checkout.js';
      el.onload = () => resolve();
      el.onerror = () => { loader = null; reject(new Error('Could not load the payment window. Check your connection.')); };
      document.body.appendChild(el);
    });
  }
  return loader;
}

export class CheckoutDismissed extends Error {
  constructor() { super('Payment cancelled'); }
}

/** Opens Razorpay Checkout. Resolves with Razorpay's success payload (payment id +
 *  signature etc.), rejects with CheckoutDismissed if the user closes the window, or
 *  an Error carrying Razorpay's description if the payment fails. */
export async function openCheckout(options: Record<string, unknown>): Promise<Record<string, string>> {
  await loadCheckoutScript();
  return new Promise((resolve, reject) => {
    const rzp = new window.Razorpay({
      theme: { color: '#c1272d' },
      ...options,
      handler: (res: Record<string, string>) => resolve(res),
      modal: { ondismiss: () => reject(new CheckoutDismissed()) },
    });
    rzp.on('payment.failed', (res: any) => reject(new Error(res?.error?.description || 'Payment failed')));
    rzp.open();
  });
}
