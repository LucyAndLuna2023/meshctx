/**
 * MeshCtx Auth — Supabase (Email + GitHub) + Password Reset + i18n
 */

// ═══ CONFIG ═══
var SUPABASE_URL = 'https://xtyjsjlkljzdgvqpskyk.supabase.co';
var SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inh0eWpzamxrbGp6ZGd2cXBza3lrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODQyNjk1NTAsImV4cCI6MjA5OTg0NTU1MH0.lFjTZ3LltOTiSXtBVtH0TD31Rrp8dLnHtmaMFNRNpfE';
var _sb = null;
var _user = null;

// ═══ i18n helpers (L & switchLang from index.html / profile.html) ═══
function _t(key, fallback) {
    try {
        if (typeof L !== 'undefined' && L && L['en'] && L['en'][key] !== undefined)
            return L['en'][key];
    } catch(e) {}
    return fallback || key;
}

function _refreshAuthI18n() {
    // Re-apply translations to auth modal (since it's hidden, we trigger on open)
    if (typeof switchLang !== 'function') return;
    try { switchLang((typeof L !== 'undefined' && L && Object.keys(L).length) ? (localStorage.getItem('meshctx-lang') || 'en') : 'en'); } catch(e) {}
}

function _getSupabase() {
    if (!_sb && SUPABASE_URL) {
        try {
            if (typeof window.supabase !== 'undefined' && window.supabase.createClient) {
                _sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
            }
        } catch(e) { console.error('Supabase init failed:', e); }
    }
    return _sb;
}

// ═══ Modal ═══
function showAuthModal(tab) {
    tab = tab || 'signin';
    var modal = document.getElementById('auth-modal');
    if (!modal) return;
    document.querySelectorAll('.auth-tab-content').forEach(function(el) { el.style.display = 'none'; });
    document.querySelectorAll('.auth-tab-btn').forEach(function(el) { el.classList.remove('active'); });
    var content = document.getElementById('auth-tab-' + tab);
    var btn = document.getElementById('auth-tab-btn-' + tab);
    if (content) content.style.display = 'block';
    if (btn) btn.classList.add('active');
    if (tab === 'signup') { generateCaptcha(); }
    if (tab === 'signin') { generateCaptchaSignin(); }
    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';
    clearAuthError();
    _refreshAuthI18n();
}

function hideAuthModal() {
    var modal = document.getElementById('auth-modal');
    if (!modal) return;
    modal.style.display = 'none';
    document.body.style.overflow = '';
    clearAuthError();
}

function clearAuthError() {
    var errs = document.querySelectorAll('.auth-error');
    errs.forEach(function(el) { el.textContent = ''; });
}

function showAuthError(msg) {
    var errs = document.querySelectorAll('.auth-error');
    errs.forEach(function(el) { el.textContent = msg; });
}

// ═══ Password Strength ═══
// Requires: 8+ chars, uppercase, lowercase, digit
function isPasswordStrong(pw) {
    return pw && pw.length >= 8 && /[A-Z]/.test(pw) && /[a-z]/.test(pw) && /[0-9]/.test(pw);
}

function checkPasswordStrength() {
    var pw = document.getElementById('signup-password');
    var bar = document.getElementById('pwd-strength-bar');
    var wrap = document.querySelector('.pwd-strength-wrap');
    if (!pw || !bar) return;
    var v = pw.value;
    if (!v) { if (wrap) wrap.style.display = 'none'; return; }
    if (wrap) wrap.style.display = 'block';
    var score = 0;
    if (v) score += Math.min(v.length, 12);
    if (/[a-z]/.test(v)) score += 3;
    if (/[A-Z]/.test(v)) score += 3;
    if (/[0-9]/.test(v)) score += 3;
    if (/[^A-Za-z0-9]/.test(v)) score += 4;
    var pct = Math.min(score / 25 * 100, 100);
    bar.style.width = pct + '%';
    bar.className = 'pwd-strength-fill s' + (pct < 40 ? '1' : pct < 70 ? '2' : '3');
}

// ═══ CAPTCHA ═══
var _captchaCode = '';

function generateCaptcha() {
    var chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
    var code = '';
    for (var i = 0; i < 6; i++) { code += chars[Math.floor(Math.random() * chars.length)]; }
    _captchaCode = code;
    var canvas = document.getElementById('captcha-canvas');
    if (!canvas) return;
    var ctx = canvas.getContext('2d');
    canvas.width = 140; canvas.height = 48;
    // Background
    ctx.fillStyle = 'rgba(30,35,50,1)';
    ctx.fillRect(0, 0, 140, 48);
    // Noise lines
    for (var i = 0; i < 6; i++) {
        ctx.strokeStyle = 'rgba(139,92,246,' + (0.15 + Math.random() * 0.2) + ')';
        ctx.beginPath();
        ctx.moveTo(Math.random() * 140, Math.random() * 48);
        ctx.lineTo(Math.random() * 140, Math.random() * 48);
        ctx.stroke();
    }
    // Noise dots
    for (var i = 0; i < 30; i++) {
        ctx.fillStyle = 'rgba(255,255,255,' + (0.05 + Math.random() * 0.15) + ')';
        ctx.fillRect(Math.random() * 140, Math.random() * 48, 2, 2);
    }
    // Draw text
    for (var i = 0; i < 6; i++) {
        ctx.font = (20 + Math.random() * 6) + 'px monospace';
        ctx.fillStyle = 'hsl(' + (260 + Math.random() * 40) + ', 70%, ' + (60 + Math.random() * 25) + '%)';
        ctx.save();
        ctx.translate(10 + i * 22, 28 + Math.random() * 10 - 5);
        ctx.rotate((Math.random() - 0.5) * 0.6);
        ctx.fillText(code[i], 0, 0);
        ctx.restore();
    }
}

function _captcha_err_alt() { return 'Incorrect verification code.'; }

function generateCaptchaSignin() {
    var chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
    var code = '';
    for (var i = 0; i < 6; i++) { code += chars[Math.floor(Math.random() * chars.length)]; }
    _captchaCodeSignin = code;
    var canvas = document.getElementById('captcha-canvas-signin');
    if (!canvas) return;
    var ctx = canvas.getContext('2d');
    canvas.width = 140; canvas.height = 48;
    ctx.fillStyle = 'rgba(30,35,50,1)';
    ctx.fillRect(0, 0, 140, 48);
    for (var i = 0; i < 6; i++) {
        ctx.strokeStyle = 'rgba(139,92,246,' + (0.15 + Math.random() * 0.2) + ')';
        ctx.beginPath();
        ctx.moveTo(Math.random() * 140, Math.random() * 48);
        ctx.lineTo(Math.random() * 140, Math.random() * 48);
        ctx.stroke();
    }
    for (var i = 0; i < 30; i++) {
        ctx.fillStyle = 'rgba(255,255,255,' + (0.05 + Math.random() * 0.15) + ')';
        ctx.fillRect(Math.random() * 140, Math.random() * 48, 2, 2);
    }
    for (var i = 0; i < 6; i++) {
        ctx.font = (20 + Math.random() * 6) + 'px monospace';
        ctx.fillStyle = 'hsl(' + (260 + Math.random() * 40) + ', 70%, ' + (60 + Math.random() * 25) + '%)';
        ctx.save();
        ctx.translate(10 + i * 22, 28 + Math.random() * 10 - 5);
        ctx.rotate((Math.random() - 0.5) * 0.6);
        ctx.fillText(code[i], 0, 0);
        ctx.restore();
    }
}
var _captchaCodeSignin = '';

// ═══ Email Sign Up ═══
async function signUpWithEmail() {
    console.log('[Auth] signUpWithEmail called');
    var sb = _getSupabase();
    console.log('[Auth] sb:', !!sb);
    if (!sb) { showAuthError('Connection error. Please refresh the page and try again.'); return; }
    var email = document.getElementById('signup-email').value.trim();
    var password = document.getElementById('signup-password').value;
    var name = document.getElementById('signup-name').value.trim();
    if (!email || !password) { showAuthError(_t('auth_err_empty', 'Please fill in email and password.')); return; }
    if (!isPasswordStrong(password)) { showAuthError(_t('auth_err_pwd_weak', 'Password must be 8+ chars with uppercase, lowercase, and number.')); return; }

    var password2 = document.getElementById('signup-password2').value;
    if (password !== password2) { showAuthError(_t('auth_err_pw_match', 'Passwords do not match.')); return; }

    // CAPTCHA
    var captchaInput = document.getElementById('signup-captcha');
    if (captchaInput && captchaInput.value.trim().toUpperCase() !== _captchaCode) {
        showAuthError(_t('auth_err_captcha', _captcha_err_alt())); generateCaptcha(); return;
    }

    var btn = document.getElementById('signup-btn');
    btn.disabled = true; btn.textContent = 'Creating account...';

    try {
    var { data, error } = await sb.auth.signUp({
        email: email,
        password: password,
        options: {
            data: { full_name: name || email.split('@')[0] },
            emailRedirectTo: window.location.origin + '/'
        }
    });
    btn.disabled = false; btn.textContent = 'Create Account';

    if (error) { showAuthError(error.message); return; }

    if (data.user && data.user.identities && data.user.identities.length === 0) {
        showAuthError('This email is already registered. Please sign in instead.');
    } else {
        showAuthError(_t('auth_confirm', 'Check your email for a confirmation link!'));
    }
    } catch(e) { btn.disabled = false; btn.textContent = 'Create Account'; showAuthError('Network error. Please check your connection and try again.'); }
}

// ═══ Email Sign In ═══
async function signInWithEmail() {
    var sb = _getSupabase();
    if (!sb) { showAuthError('Connection error. Please refresh the page and try again.'); return; }
    var email = document.getElementById('signin-email').value.trim();
    var password = document.getElementById('signin-password').value;
    if (!email || !password) { showAuthError(_t('auth_err_empty', 'Please fill in email and password.')); return; }

    // CAPTCHA
    var captchaInput = document.getElementById('signin-captcha');
    if (captchaInput && captchaInput.value.trim().toUpperCase() !== _captchaCodeSignin) {
        showAuthError(_t('auth_err_captcha', _captcha_err_alt())); generateCaptchaSignin(); return;
    }

    var btn = document.getElementById('signin-btn');
    btn.disabled = true; btn.textContent = 'Signing in...';

    var { data, error } = await sb.auth.signInWithPassword({ email: email, password: password });
    btn.disabled = false; btn.textContent = 'Sign In';

    if (error) { showAuthError(error.message); return; }
    _user = data.user;
    updateAuthUI();
    hideAuthModal();
}

// ═══ OAuth (GitHub) ═══
async function signInWithOAuth(provider) {
    var sb = _getSupabase();
    if (!sb) { showAuthError('Supabase not configured.'); return; }

    var btn = document.getElementById('oauth-btn-' + provider);
    if (btn) { btn.disabled = true; }

    var { data, error } = await sb.auth.signInWithOAuth({
        provider: provider,
        options: { redirectTo: window.location.origin + '/' }
    });
    if (error) {
        showAuthError(error.message);
        if (btn) { btn.disabled = false; }
    }
}

// ═══ Forgot / Reset Password ═══
function showResetPassword() {
    document.querySelectorAll('.auth-tab-content').forEach(function(el) { el.style.display = 'none'; });
    var tab = document.getElementById('auth-tab-reset');
    if (tab) tab.style.display = 'block';
    var err = document.getElementById('auth-error-reset');
    if (err) err.textContent = '';
}

async function resetPassword() {
    var sb = _getSupabase();
    if (!sb) { showAuthError('Connection error. Please refresh the page and try again.'); return; }
    var email = document.getElementById('reset-email').value.trim();
    if (!email) {
        var err = document.getElementById('auth-error-reset');
        if (err) err.textContent = _t('auth_err_empty', 'Please fill in your email.');
        return;
    }
    var btn = document.getElementById('reset-btn');
    btn.disabled = true;
    var { error } = await sb.auth.resetPasswordForEmail(email, { redirectTo: window.location.origin + '/' });
    btn.disabled = false;
    var err = document.getElementById('auth-error-reset');
    if (error) { if (err) err.textContent = error.message; }
    else { if (err) err.textContent = _t('auth_reset_sent', 'Check your email for the reset link!'); }
}

// ═══ Change Password ═══
async function changePassword(newPassword) {
    var sb = _getSupabase();
    if (!sb || !_user) return { error: { message: 'Not logged in' } };
    if (!newPassword || newPassword.length < 6) return { error: { message: _t('auth_err_pwd_short', 'Password must be at least 6 characters.') } };
    var { data, error } = await sb.auth.updateUser({ password: newPassword });
    return { data: data, error: error };
}

// ═══ Sign Out ═══
async function signOut() {
    var sb = _getSupabase();
    if (!sb) { showAuthError('Connection error. Please refresh the page and try again.'); return; }
    await sb.auth.signOut();
    _user = null;
    updateAuthUI();
}

// ═══ Update Nav UI ═══
function updateAuthUI() {
    var authBtn = document.getElementById('auth-btn');
    var userMenu = document.getElementById('user-menu');
    var userName = document.getElementById('user-name');
    var userAvatar = document.getElementById('user-avatar');

    if (_user) {
        if (authBtn) authBtn.style.display = 'none';
        if (userMenu) userMenu.style.display = 'flex';
        if (userName) {
            var meta = _user.user_metadata || {};
            userName.textContent = meta.full_name || meta.user_name || _user.email || 'User';
        }
        if (userAvatar) {
            var avatarUrl = (_user.user_metadata || {}).avatar_url || '';
            if (avatarUrl) { userAvatar.src = avatarUrl; userAvatar.style.display = 'inline'; }
            else { userAvatar.style.display = 'none'; }
        }
        // Unlock gated content
        document.querySelectorAll('.auth-gated-overlay').forEach(function(el) { el.classList.add('unlocked'); });
    } else {
        if (authBtn) authBtn.style.display = 'inline-flex';
        if (userMenu) userMenu.style.display = 'none';
        // Lock gated content
        document.querySelectorAll('.auth-gated-overlay').forEach(function(el) { el.classList.remove('unlocked'); });
    }
}

// ═══ Profile Management ═══
async function updateProfile(fields) {
    var sb = _getSupabase();
    if (!sb || !_user) return { error: 'Not logged in' };

    var updates = { data: {} };
    if (fields.email) updates.email = fields.email;
    if (fields.password) updates.password = fields.password;
    if (fields.full_name !== undefined) updates.data.full_name = fields.full_name;
    if (fields.avatar_url !== undefined) updates.data.avatar_url = fields.avatar_url;
    if (fields.bio !== undefined) updates.data.bio = fields.bio;
    if (fields.website !== undefined) updates.data.website = fields.website;
    if (fields.company !== undefined) updates.data.company = fields.company;

    var { data, error } = await sb.auth.updateUser(updates);
    if (!error) {
        _user = data.user;
        updateAuthUI();
    }
    return { data: data, error: error };
}

async function addEmail(newEmail) {
    var sb = _getSupabase();
    if (!sb) return { error: 'Not logged in' };
    // Supabase doesn't have direct "add email" — we update the primary email
    // For multiple emails, we'd need a custom table
    return await sb.auth.updateUser({ email: newEmail });
}

// ═══ Init ═══
async function initAuth() {
    var sb = _getSupabase();
    if (!sb) {
        var authBtn = document.getElementById('auth-btn');
        if (authBtn) authBtn.style.display = 'none';
        return;
    }

    try {
        var { data } = await sb.auth.getSession();
        if (data && data.session) { _user = data.session.user; }
    } catch(e) { console.log('No active session'); }

    updateAuthUI();

    sb.auth.onAuthStateChange(function(event, session) {
        _user = session ? session.user : null;
        updateAuthUI();
        if (event === 'SIGNED_IN') {
            hideAuthModal();
            console.log('Signed in:', _user && _user.email);
        }
    });
}

// Keyboard shortcut
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') hideAuthModal();
});

document.addEventListener('DOMContentLoaded', initAuth);
