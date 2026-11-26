/* GovFleet sign-in page (Firebase Authentication).
 *
 * The browser signs in with Firebase (email/password or Google), then sends
 * the fresh ID token to Django, which verifies it with firebase-admin,
 * applies the email-format and role rules, and starts a session.
 * The server is the authority; the checks here are only for quick feedback.
 * All text is inserted with textContent. */

const root = document.getElementById("auth");
const resultBox = document.getElementById("auth-result");
const config = JSON.parse(document.getElementById("firebase-config").textContent);

const USER_EMAIL = /^[a-z]{2,64}@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.gov\.ph$/;
const ADMIN_EMAIL = /^govfleetadmin\d{2}@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.gov\.ph$/;

const FIREBASE_ERRORS = {
  "auth/invalid-credential": "Incorrect email or password.",
  "auth/wrong-password": "Incorrect email or password.",
  "auth/user-not-found": "Incorrect email or password.",
  "auth/invalid-email": "Enter a valid email address.",
  "auth/email-already-in-use": "An account with this email already exists. Sign in instead.",
  "auth/weak-password": "Choose a stronger password (at least 8 characters).",
  "auth/too-many-requests": "Too many attempts. Please wait a moment and try again.",
  "auth/network-request-failed": "Network error. Please check your connection and try again.",
  "auth/user-disabled": "This account has been disabled.",
  "auth/popup-blocked": "The sign-in pop-up was blocked. Allow pop-ups for this site and try again.",
  "auth/unauthorized-domain": "This site is not authorised for sign-in. Contact the system administrator.",
};

function show(kind, text) {
  resultBox.className = `alert ${kind}`;
  resultBox.textContent = text;
  resultBox.hidden = false;
}

function clearMessage() {
  resultBox.hidden = true;
  resultBox.textContent = "";
}

function firebaseMessage(err) {
  return FIREBASE_ERRORS[err && err.code] || "Sign-in failed. Please try again.";
}

function getCookie(name) {
  const match = document.cookie.split("; ").find((row) => row.startsWith(name + "="));
  return match ? decodeURIComponent(match.split("=")[1]) : "";
}

function normalize(email) {
  return (email || "").trim().toLowerCase();
}

function setBusy(busy) {
  root.querySelectorAll("button").forEach((b) => { b.disabled = busy; });
}

if (!Object.values(config).every(Boolean)) {
  setBusy(true);
  throw new Error("Firebase web config missing");
}

const { initializeApp } = await import(root.dataset.appUrl);
const fb = await import(root.dataset.authUrl);
const auth = fb.getAuth(initializeApp(config));

if (new URLSearchParams(window.location.search).has("signed_out")) {
  await fb.signOut(auth);
}

// --- tabs --------------------------------------------------------------------

const signinForm = document.getElementById("signin-form");
const signupForm = document.getElementById("signup-form");
const tabs = { signin: document.getElementById("tab-signin"), signup: document.getElementById("tab-signup") };

function selectTab(name) {
  clearMessage();
  signinForm.hidden = name !== "signin";
  signupForm.hidden = name !== "signup";
  tabs.signin.setAttribute("aria-selected", String(name === "signin"));
  tabs.signup.setAttribute("aria-selected", String(name === "signup"));
}
tabs.signin.addEventListener("click", () => selectTab("signin"));
tabs.signup.addEventListener("click", () => selectTab("signup"));

// --- email verification panel ---------------------------------------------------

const verifyPanel = document.getElementById("verify-panel");
const verifyText = document.getElementById("verify-text");

function showVerify(email, justSent) {
  verifyText.textContent = justSent
    ? `We sent a verification link to ${email}. Open it, then come back and continue.`
    : `${email} is not verified yet. Open the link we emailed you, then continue.`;
  verifyPanel.hidden = false;
}

document.getElementById("verify-resend").addEventListener("click", async () => {
  if (!auth.currentUser) return;
  try {
    await fb.sendEmailVerification(auth.currentUser);
    show("ok", "Verification email sent again.");
  } catch (err) {
    show("error", firebaseMessage(err));
  }
});

document.getElementById("verify-done").addEventListener("click", async () => {
  if (!auth.currentUser) return;
  await auth.currentUser.reload();
  await startSession(auth.currentUser);
});

// --- Firebase -> Django session --------------------------------------------------

async function startSession(user) {
  clearMessage();
  if (!user.emailVerified) {
    showVerify(user.email, false);
    return;
  }
  setBusy(true);
  try {
    const idToken = await user.getIdToken(true);
    const response = await fetch(root.dataset.sessionUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": getCookie("csrftoken") },
      body: JSON.stringify({ idToken, next: root.dataset.next }),
    });
    let body = {};
    try { body = await response.json(); } catch (_) { /* empty */ }

    if (response.ok && body.redirect) {
      window.location.assign(body.redirect);
      return;
    }
    if (response.status === 429) show("error", "Too many sign-in attempts. Please wait a minute and try again.");
    else if (response.status === 503) show("error", "Sign-in is temporarily unavailable. Please try again shortly.");
    else show("error", body.detail || "Sign-in failed. Please try again.");
    if (response.status === 403) await fb.signOut(auth);
  } catch (_) {
    show("error", "Network error. Please check your connection and try again.");
  } finally {
    setBusy(false);
  }
}

// --- actions ------------------------------------------------------------------

signinForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearMessage();
  verifyPanel.hidden = true;
  const email = normalize(document.getElementById("signin-email").value);
  const password = document.getElementById("signin-password").value;
  if (!email || !password) return show("error", "Enter your email and password.");
  setBusy(true);
  try {
    const cred = await fb.signInWithEmailAndPassword(auth, email, password);
    await startSession(cred.user);
  } catch (err) {
    show("error", firebaseMessage(err));
  } finally {
    setBusy(false);
  }
});

signupForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearMessage();
  const email = normalize(document.getElementById("signup-email").value);
  const password = document.getElementById("signup-password").value;
  const confirm = document.getElementById("signup-confirm").value;
  if (ADMIN_EMAIL.test(email)) return show("error", "Admin accounts are created by an existing Admin, not here.");
  if (!USER_EMAIL.test(email)) return show("error", "Use your agency email in the form firstnamelastname@agency.gov.ph.");
  if (password.length < 8) return show("error", "Choose a password with at least 8 characters.");
  if (password !== confirm) return show("error", "The passwords do not match.");
  setBusy(true);
  try {
    const cred = await fb.createUserWithEmailAndPassword(auth, email, password);
    await fb.sendEmailVerification(cred.user);
    showVerify(email, true);
  } catch (err) {
    show("error", firebaseMessage(err));
  } finally {
    setBusy(false);
  }
});

document.getElementById("google-signin").addEventListener("click", async () => {
  clearMessage();
  verifyPanel.hidden = true;
  setBusy(true);
  try {
    const cred = await fb.signInWithPopup(auth, new fb.GoogleAuthProvider());
    await startSession(cred.user);
  } catch (err) {
    if (err && (err.code === "auth/popup-closed-by-user" || err.code === "auth/cancelled-popup-request")) return;
    show("error", firebaseMessage(err));
  } finally {
    setBusy(false);
  }
});

document.getElementById("forgot-password").addEventListener("click", async () => {
  clearMessage();
  const email = normalize(document.getElementById("signin-email").value);
  if (!email) return show("error", "Enter your email above first.");
  try {
    await fb.sendPasswordResetEmail(auth, email);
  } catch (_) { /* same message either way (no account enumeration) */ }
  show("ok", "If an account exists for that email, a password reset link has been sent.");
});
