/**
 * MeshCtx Auth — Supabase (Email + GitHub + Google) + i18n
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
        _sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
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
    var el = document.getElementById('auth-error');
    if (el) el.textContent = '';
}

function showAuthError(msg) {
    var el = document.getElementById('auth-error');
    if (el) el.textContent = msg;
}

// ═══ Email Sign Up ═══
async function signUpWithEmail() {
    var sb = _getSupabase();
    if (!sb) return;
    var email = document.getElementById('signup-email').value.trim();
    var password = document.getElementById('signup-password').value;
    var name = document.getElementById('signup-name').value.trim();
    if (!email || !password) { showAuthError(_t('auth_err_empty', 'Please fill in email and password.')); return; }
    if (password.length < 6) { showAuthError(_t('auth_err_short', 'Password must be at least 6 characters.')); return; }

    var btn = document.getElementById('signup-btn');
    btn.disabled = true; btn.textContent = 'Creating account...';

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
}

// ═══ Email Sign In ═══
async function signInWithEmail() {
    var sb = _getSupabase();
    if (!sb) return;
    var email = document.getElementById('signin-email').value.trim();
    var password = document.getElementById('signin-password').value;
    if (!email || !password) { showAuthError(_t('auth_err_empty', 'Please fill in email and password.')); return; }

    var btn = document.getElementById('signin-btn');
    btn.disabled = true; btn.textContent = 'Signing in...';

    var { data, error } = await sb.auth.signInWithPassword({ email: email, password: password });
    btn.disabled = false; btn.textContent = 'Sign In';

    if (error) { showAuthError(error.message); return; }
    _user = data.user;
    updateAuthUI();
    hideAuthModal();
}

// ═══ OAuth (GitHub / Google) ═══
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

// ═══ Sign Out ═══
async function signOut() {
    var sb = _getSupabase();
    if (!sb) return;
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
    } else {
        if (authBtn) authBtn.style.display = 'inline-flex';
        if (userMenu) userMenu.style.display = 'none';
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
