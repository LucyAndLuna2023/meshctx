/**
 * MeshCtx Auth — Supabase + GitHub OAuth
 * 
 * Setup (manual):
 * 1. https://supabase.com → New Project → get URL + anon key
 * 2. Supabase Dashboard → Authentication → Providers → GitHub → enable
 * 3. GitHub → Settings → Developer settings → OAuth Apps → New
 *    - Callback URL: https://<project>.supabase.co/auth/v1/callback
 *    - Copy Client ID + Client Secret to Supabase GitHub provider
 * 4. Fill in SUPABASE_URL and SUPABASE_ANON_KEY below
 */

// ═══ CONFIG — 填你的 Supabase 信息 ═══
var SUPABASE_URL = 'https://xtyjsjlkljzdgvqpskyk.supabase.co';
var SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inh0eWpzamxrbGp6ZGd2cXBza3lrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODQyNjk1NTAsImV4cCI6MjA5OTg0NTU1MH0.lFjTZ3LltOTiSXtBVtH0TD31Rrp8dLnHtmaMFNRNpfE';

var _sb = null;
var _user = null;

function _getSupabase() {
    if (!_sb && SUPABASE_URL && SUPABASE_URL.indexOf('__') === -1) {
        _sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
    }
    return _sb;
}

// ═══ Auth Modal ═══
function showAuthModal() {
    var modal = document.getElementById('auth-modal');
    if (!modal) return;
    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';
}

function hideAuthModal() {
    var modal = document.getElementById('auth-modal');
    if (!modal) return;
    modal.style.display = 'none';
    document.body.style.overflow = '';
}

// ═══ GitHub OAuth Login ═══
async function signInWithGitHub() {
    var sb = _getSupabase();
    if (!sb) { alert('Supabase not configured. Check SUPABASE_URL in auth.js'); return; }
    
    var btn = document.getElementById('github-login-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Connecting...'; }
    
    try {
        var { data, error } = await sb.auth.signInWithOAuth({
            provider: 'github',
            options: { redirectTo: window.location.origin + '/' }
        });
        if (error) throw error;
        // Will redirect to GitHub
    } catch(e) {
        console.error('GitHub OAuth error:', e);
        if (btn) { btn.disabled = false; btn.textContent = 'Sign in with GitHub'; }
        alert('Login failed: ' + e.message);
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

// ═══ Update UI based on auth state ═══
function updateAuthUI() {
    var authBtn = document.getElementById('auth-btn');
    var userAvatar = document.getElementById('user-avatar');
    var userName = document.getElementById('user-name');
    var userMenu = document.getElementById('user-menu');
    
    if (_user) {
        // Logged in
        if (authBtn) authBtn.style.display = 'none';
        if (userMenu) userMenu.style.display = 'flex';
        if (userName) userName.textContent = _user.user_metadata?.full_name || _user.user_metadata?.user_name || _user.email || 'User';
        if (userAvatar) {
            var avatarUrl = _user.user_metadata?.avatar_url || '';
            if (avatarUrl) {
                userAvatar.src = avatarUrl;
                userAvatar.style.display = 'inline';
            } else {
                userAvatar.style.display = 'none';
            }
        }
    } else {
        // Logged out
        if (authBtn) authBtn.style.display = 'inline-flex';
        if (userMenu) userMenu.style.display = 'none';
    }
}

// ═══ Init ═══
async function initAuth() {
    var sb = _getSupabase();
    if (!sb) {
        // Supabase not configured — hide auth button
        var authBtn = document.getElementById('auth-btn');
        if (authBtn) authBtn.style.display = 'none';
        return;
    }
    
    // Check existing session
    try {
        var { data } = await sb.auth.getSession();
        if (data && data.session) {
            _user = data.session.user;
        }
    } catch(e) {
        console.log('No active session');
    }
    
    updateAuthUI();
    
    // Listen for auth changes
    sb.auth.onAuthStateChange(function(event, session) {
        _user = session ? session.user : null;
        updateAuthUI();
        if (event === 'SIGNED_IN') {
            hideAuthModal();
            console.log('User signed in:', _user?.email);
        }
    });
}

// Auto-init
document.addEventListener('DOMContentLoaded', initAuth);
