/**
 * Libraire — inject universal marketing footer into #bb-footer-slot.
 */
(function () {
  "use strict";
  var slot = document.getElementById("bb-footer-slot");
  if (!slot) return;

  var html =
    '<footer class="relative z-10 border-t border-stone-200 bg-gradient-to-b from-parchment-50 to-stone-100 dark:border-stone-800 dark:from-stone-950 dark:to-stone-900">' +
    '  <div class="mx-auto max-w-6xl px-4 pt-14 pb-8 sm:px-6">' +
    '    <div class="grid gap-10 sm:grid-cols-2 lg:grid-cols-4">' +
    '      <div class="lg:col-span-1">' +
    '        <a href="/frontend/index.html" class="mb-4 inline-flex items-center gap-2.5">' +
    '          <span class="text-2xl leading-none" aria-hidden="true">📚</span>' +
    '          <span class="font-serif-display text-lg font-semibold text-stone-800 dark:text-stone-100">Libraire</span>' +
    "        </a>" +
    '        <p class="text-sm leading-relaxed text-stone-500 dark:text-stone-400">Read Less. Know More. Build Your AI-Powered Mind Library.</p>' +
    '        <div class="mt-5"><a href="mailto:hi@bookbriefai.com" class="text-xs font-medium text-amber-800 hover:underline dark:text-amber-400">✉ hi@bookbriefai.com</a></div>' +
    "      </div>" +
    "      <div>" +
    '        <h4 class="mb-4 text-xs font-bold uppercase tracking-widest text-stone-400 dark:text-stone-500">Product</h4>' +
    '        <ul class="space-y-2.5 text-sm">' +
    '          <li><a href="/frontend/features.html" class="text-stone-600 transition-colors hover:text-amber-800 dark:text-stone-400 dark:hover:text-amber-400">Features</a></li>' +
    '          <li><a href="/frontend/how-it-works.html" class="text-stone-600 transition-colors hover:text-amber-800 dark:text-stone-400 dark:hover:text-amber-400">How It Works</a></li>' +
    '          <li><a href="/frontend/pricing.html" class="text-stone-600 transition-colors hover:text-amber-800 dark:text-stone-400 dark:hover:text-amber-400">Pricing</a></li>' +
    '          <li><a href="/frontend/faq.html" class="text-stone-600 transition-colors hover:text-amber-800 dark:text-stone-400 dark:hover:text-amber-400">FAQ</a></li>' +
    "        </ul>" +
    "      </div>" +
    "      <div>" +
    '        <h4 class="mb-4 text-xs font-bold uppercase tracking-widest text-stone-400 dark:text-stone-500">Account</h4>' +
    '        <ul class="space-y-2.5 text-sm">' +
    '          <li><a href="/frontend/login.html" class="text-stone-600 transition-colors hover:text-amber-800 dark:text-stone-400 dark:hover:text-amber-400">Log In</a></li>' +
    '          <li><a href="/frontend/login.html?mode=register" class="text-stone-600 transition-colors hover:text-amber-800 dark:text-stone-400 dark:hover:text-amber-400">Sign Up Free</a></li>' +
    '          <li><a href="/frontend/dashboard.html" class="text-stone-600 transition-colors hover:text-amber-800 dark:text-stone-400 dark:hover:text-amber-400">Dashboard</a></li>' +
    '          <li><a href="/health" class="text-stone-600 transition-colors hover:text-amber-800 dark:text-stone-400 dark:hover:text-amber-400">API status</a></li>' +
    "        </ul>" +
    "      </div>" +
    "      <div>" +
    '        <h4 class="mb-4 text-xs font-bold uppercase tracking-widest text-stone-400 dark:text-stone-500">Legal</h4>' +
    '        <ul class="space-y-2.5 text-sm">' +
    '          <li><a href="/frontend/privacy.html" class="text-stone-600 transition-colors hover:text-amber-800 dark:text-stone-400 dark:hover:text-amber-400">Privacy Policy</a></li>' +
    '          <li><a href="/frontend/cookies.html" class="text-stone-600 transition-colors hover:text-amber-800 dark:text-stone-400 dark:hover:text-amber-400">Cookies Policy</a></li>' +
    '          <li><a href="/frontend/terms.html" class="text-stone-600 transition-colors hover:text-amber-800 dark:text-stone-400 dark:hover:text-amber-400">Terms &amp; Conditions</a></li>' +
    '          <li><a href="/frontend/contact.html" class="text-stone-600 transition-colors hover:text-amber-800 dark:text-stone-400 dark:hover:text-amber-400">Contact Us</a></li>' +
    "        </ul>" +
    "      </div>" +
    "    </div>" +
    "  </div>" +
    '  <div class="border-t border-stone-200 dark:border-stone-800">' +
    '    <div class="mx-auto flex max-w-6xl flex-col gap-2 px-4 py-5 sm:flex-row sm:items-center sm:justify-between sm:px-6">' +
    '      <p class="text-center text-xs text-stone-400 dark:text-stone-500 sm:text-left">© 2026 Libraire. All rights reserved.</p>' +
    '      <p class="text-center text-xs text-stone-500 dark:text-stone-400 sm:text-right">Made with <span aria-hidden="true">❤️</span> for readers everywhere</p>' +
    "    </div>" +
    "  </div>" +
    "</footer>";

  slot.outerHTML = html;
})();
