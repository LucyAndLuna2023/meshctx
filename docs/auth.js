/**
 * MeshCtx Auth — Supabase (Email + GitHub) + Password Reset + i18n
 */

// ═══ CONFIG ═══
var SUPABASE_URL = /* meshctx config — immutable */ 'https://xtyjsjlkljzdgvqpskyk.supabase.co';
var SUPABASE_ANON_KEY = /* meshctx config — immutable */ 'sb_publishable_y3oQKcnr2dADsN39_PSBvg_H3Qbm5Bf';
var _sb = null;
var _user = null;

// ═══ i18n helpers (L & switchLang from index.html / profile.html) ═══
function _t(key, fallback) {
    try {
        var lang = localStorage.getItem('meshctx-lang') || 'en';
        if (typeof L !== 'undefined' && L && L[lang] && L[lang][key] !== undefined)
            return L[lang][key];
        // Fallback to en if current lang missing this key
        if (lang !== 'en' && L && L['en'] && L['en'][key] !== undefined)
            return L['en'][key];
    } catch(e) {}
    return fallback || key;
}

var __lastI18nLang = null;
function _refreshAuthI18n() {
    // Re-apply translations to auth modal only when language changed
    var cur = localStorage.getItem('meshctx-lang') || 'en';
    if (cur === __lastI18nLang) return;
    __lastI18nLang = cur;
    if (typeof switchLang !== 'function') return;
    try { switchLang((typeof L !== 'undefined' && L && Object.keys(L).length) ? cur : 'en'); } catch(e) {}
}

function _getSupabase() {
    var url = SUPABASE_URL;
    var key = SUPABASE_ANON_KEY;
    // Return null if misconfigured so callers can guard
    if (!url || !key || key.indexOf('sb_publishable') !== 0) return null;
    return {
        auth: {
            signUp: function(params) {
                // Flatten Supabase SDK options format to REST API format
                var body = { email: params.email, password: params.password };
                if (params.options) {
                    if (params.options.data) body.data = params.options.data;
                    if (params.options.emailRedirectTo) body.redirect_to = params.options.emailRedirectTo;
                }
                return fetch(SUPABASE_URL + '/auth/v1/signup', {
                    method: 'POST',
                    headers: {'apikey': SUPABASE_ANON_KEY, 'Content-Type': 'application/json'},
                    body: JSON.stringify(body)
                }).then(function(r){ return r.json().then(function(d){
                    if (r.ok) {
                        // Signup returns session only if email confirmation is OFF
                        var session = null;
                        if (d.access_token) {
                            session = { access_token: d.access_token, refresh_token: d.refresh_token, expires_in: d.expires_in, user: d.user };
                        }
                        return {data: {user: d.user || d, session: session}, error: null};
                    }
                    return {data: null, error: {message: d.msg || d.message || JSON.stringify(d)}};
                }); })
                .catch(function(e){ return {data: null, error: {message: 'Network error: ' + (e.message || 'connection failed')}}; });
            },
            signInWithPassword: function(params) {
                return fetch(SUPABASE_URL + '/auth/v1/token?grant_type=password', {
                    method: 'POST',
                    headers: {'apikey': SUPABASE_ANON_KEY, 'Content-Type': 'application/json'},
                    body: JSON.stringify(params)
                }).then(function(r){ return r.json().then(function(d){ 
                    if (r.ok) {
                        // Normalize to {user, session} like signUp
                        return {data: {
                            user: d.user,
                            session: { access_token: d.access_token, refresh_token: d.refresh_token, expires_in: d.expires_in }
                        }, error: null};
                    }
                    return {data: null, error: {message: d.msg || d.error_description || JSON.stringify(d)}};
                }); })
                .catch(function(e){ return {data: null, error: {message: 'Network error: ' + (e.message || 'connection failed')}}; });
            },
            signInWithOAuth: function(params) {
                var qs = '?provider=' + encodeURIComponent(params.provider) + '&redirect_to=' + encodeURIComponent(params.options.redirectTo);
                window.location.href = SUPABASE_URL + '/auth/v1/authorize' + qs;
                return Promise.resolve({data: {}, error: null});
            },
            resetPasswordForEmail: function(email, options) {
                var body = {email: email};
                if (options && options.redirectTo) body.redirect_to = options.redirectTo;
                return fetch(SUPABASE_URL + '/auth/v1/recover', {
                    method: 'POST',
                    headers: {'apikey': SUPABASE_ANON_KEY, 'Content-Type': 'application/json'},
                    body: JSON.stringify(body)
                }).then(function(r){ return r.json().then(function(d){
                    if (r.ok) return {data: {}, error: null};
                    return {data: null, error: {message: d.msg || d.message || 'Failed to send reset email'}};
                }); })
                .catch(function(e){ return {data: null, error: {message: 'Network error: ' + (e.message || 'connection failed')}}; });
            },
            updateUser: function(params) {
                var headers = {'apikey': SUPABASE_ANON_KEY, 'Content-Type': 'application/json'};
                if (_token) headers['Authorization'] = 'Bearer ' + _token;
                return fetch(SUPABASE_URL + '/auth/v1/user', {
                    method: 'PUT',
                    headers: headers,
                    body: JSON.stringify(params)
                }).then(function(r){ return r.json().then(function(d){ return {data: r.ok ? d : null, error: r.ok ? null : d}; }); });
            },
            getSession: function() {
                if (!_token) return Promise.resolve({data: {session: null}, error: null});
                return fetch(SUPABASE_URL + '/auth/v1/user', {
                    headers: {'apikey': SUPABASE_ANON_KEY, 'Authorization': 'Bearer ' + _token}
                }).then(function(r){ return r.json().then(function(d){ return {data: {session: {user: r.ok ? d : null}}, error: r.ok ? null : d}; }); })
                .catch(function(){ return {data: {session: null}, error: null}; });
            },
            onAuthStateChange: function(cb) { _onAuthChange = cb; },
            setSession: function(params) {
                if (!params || !params.access_token) return Promise.resolve({data: {session: null}, error: {message: 'Missing access_token'}});
                _token = params.access_token;
                if (params.refresh_token) _refreshToken = params.refresh_token;
                localStorage.setItem('meshctx-token', _token);
                if (_refreshToken) localStorage.setItem('meshctx-refresh-token', _refreshToken);
                // Fetch user with the new token
                var headers = {'apikey': SUPABASE_ANON_KEY, 'Authorization': 'Bearer ' + _token};
                return fetch(SUPABASE_URL + '/auth/v1/user', {headers: headers})
                    .then(function(r){ return r.json().then(function(d){
                        if (r.ok) {
                            _user = d;
                            if (_onAuthChange) _onAuthChange('SIGNED_IN', {user: d});
                            return {data: {session: {user: d, access_token: _token}}, error: null};
                        }
                        _token = null; _user = null;
                        return {data: {session: null}, error: {message: d.msg || 'Invalid token'}};
                    }); })
                    .catch(function(e){ return {data: {session: null}, error: {message: 'Network error: ' + e.message}}; });
            },
            signOut: function() {
                var tok = _token;
                _token = null; _user = null;
                localStorage.removeItem('meshctx-token');
                if (_onAuthChange) _onAuthChange('SIGNED_OUT', null);
                return fetch(SUPABASE_URL + '/auth/v1/logout', {
                    method: 'POST',
                    headers: {'apikey': SUPABASE_ANON_KEY, 'Authorization': 'Bearer ' + (tok || '')}
                }).catch(function(){});
            }
        }
    };
}

var _token = localStorage.getItem('meshctx-token') || null;  // ⚠️ P1: localStorage XSS risk — TODO: migrate to httpOnly cookie
var _refreshToken = localStorage.getItem('meshctx-refresh-token') || null;
var _onAuthChange = null;

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
    var text = (typeof msg === 'string') ? msg : (msg && msg.message) ? msg.message : String(msg || _t('auth_err_unknown', 'Unknown error'));
    var errs = document.querySelectorAll('.auth-error');
    for (var i = 0; i < errs.length; i++) { errs[i].textContent = text; }
    // Flash error on buttons briefly, then restore original text
    var sbtn = document.getElementById('signup-btn');
    var ibn = document.getElementById('signin-btn');
    var rbtn = document.getElementById('reset-btn');
    var btns = [sbtn, ibn, rbtn];
    for (var j = 0; j < btns.length; j++) {
        var btn = btns[j];
        if (!btn || btn.disabled) continue;
        var orig = btn.getAttribute('data-orig-text');
        if (!orig) { orig = btn.textContent; btn.setAttribute('data-orig-text', orig); }
        btn.textContent = '❌ ' + text.substring(0, 30);
        btn.style.background = '#ef4444';
        btn.disabled = false;
        (function(b, o) {
            setTimeout(function() {
                b.textContent = o;
                b.style.background = '';
            }, 3000);
        })(btn, orig);
    }
}

// ═══ Password Strength ═══
// Requires: 8+ chars, uppercase, lowercase, digit
function isPasswordStrong(pw) {
    return pw && pw.length >= 8 && /[A-Z]/.test(pw) && /[a-z]/.test(pw) && /[0-9]/.test(pw);
}

function checkPasswordStrength() {
    _checkPwdStrength('signup-password', 'pwd-strength-bar', '.pwd-strength-wrap');
}

// Generic password strength bar — usable from any page
function _checkPwdStrength(inputId, barId, wrapSelector) {
    var pw = document.getElementById(inputId);
    var bar = document.getElementById(barId);
    var wrap = document.querySelector(wrapSelector);
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
// ⚠️ P1: client-side only, no server validation — TODO: Cloudflare Turnstile or Supabase reCAPTCHA
var _captchaCode = '\u200B';   // zero-width space — never matches user input, prevents empty bypass
var _captchaCodeSignin = '\u200B';

function _captcha_err_alt() { return _t('auth_captcha_err', 'Incorrect verification code.'); }

function _drawCaptcha(canvasId) {
    var chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
    var code = '';
    for (var i = 0; i < 6; i++) { code += chars[Math.floor(Math.random() * chars.length)]; }
    var canvas = document.getElementById(canvasId);
    if (!canvas) return '';
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
    return code;
}

function generateCaptcha() { _captchaCode = _drawCaptcha('captcha-canvas'); }
function generateCaptchaSignin() { _captchaCodeSignin = _drawCaptcha('captcha-canvas-signin'); }

// ═══ Email Sign Up ═══
async function signUpWithEmail() {
    var sb = _getSupabase();
    if (!sb) { showAuthError(_t('auth_err_connection', 'Network error. Check your connection and try again.')); return; }
    var email = document.getElementById('signup-email').value.trim();
    var password = document.getElementById('signup-password').value;
    var name = document.getElementById('signup-name').value.trim();
    if (!email || !password) { showAuthError(_t('auth_err_empty', 'Please fill in email and password.')); return; }
    if (!isPasswordStrong(password)) { showAuthError(_t('auth_err_pwd_weak', 'Password must be 8+ chars with uppercase, lowercase, and number.')); return; }

    var password2 = document.getElementById('signup-password2').value;
    if (password !== password2) { showAuthError(_t('auth_err_pwd_match', 'Passwords do not match.')); return; }

    // CAPTCHA
    var captchaInput = document.getElementById('signup-captcha');
    if (captchaInput && captchaInput.value.trim().toUpperCase() !== _captchaCode) {
        showAuthError(_t('auth_captcha_err', _captcha_err_alt())); generateCaptcha(); return;
    }

    var btn = document.getElementById('signup-btn');
    if (!btn) { showAuthError(_t('auth_err_ui', 'UI error. Please refresh the page.')); return; }
    btn.disabled = true; btn.textContent = _t('auth_btn_creating', 'Creating account…');

    try {
    var { data, error } = await sb.auth.signUp({
        email: email,
        password: password,
        options: {
            data: { full_name: name || email.split('@')[0] },
            emailRedirectTo: window.location.origin + '/'
        }
    });
    btn.disabled = false; btn.textContent = _t('auth_signup_btn', 'Create Account');

    if (error) { showAuthError(error.message); return; }

    // If email confirmation is off, we get a session immediately
    if (data.session && data.session.access_token) {
        _token = data.session.access_token;
        localStorage.setItem('meshctx-token', _token);
        _user = data.session.user || data.user;
        updateAuthUI();
        hideAuthModal();
        return;
    }

    // Email confirmation is on — identities is empty [] for new users
    // "already registered" returns 422 error from Supabase, caught above
    showAuthError(_t('auth_confirm', 'Check your email for a confirmation link!'));
    } catch(e) { btn.disabled = false; btn.textContent = _t('auth_signup_btn', 'Create Account'); showAuthError(_t('auth_err_network', 'Network or server error. Please try again.')); }
}

// ═══ Email Sign In ═══
async function signInWithEmail() {
    var sb = _getSupabase();
    if (!sb) { showAuthError(_t('auth_err_connection', 'Network error. Check your connection and try again.')); return; }
    var email = document.getElementById('signin-email').value.trim();
    var password = document.getElementById('signin-password').value;
    if (!email || !password) { showAuthError(_t('auth_err_empty', 'Please fill in email and password.')); return; }

    // CAPTCHA
    var captchaInput = document.getElementById('signin-captcha');
    if (captchaInput && captchaInput.value.trim().toUpperCase() !== _captchaCodeSignin) {
        showAuthError(_t('auth_captcha_err', _captcha_err_alt())); generateCaptchaSignin(); return;
    }

    var btn = document.getElementById('signin-btn');
    btn.disabled = true; btn.textContent = _t('auth_btn_signing_in', 'Signing in…');

    try {
    var { data, error } = await sb.auth.signInWithPassword({ email: email, password: password });
    btn.disabled = false; btn.textContent = _t('auth_signin_btn', 'Sign In');

    if (error) { showAuthError(error.message); return; }
    if (!data || !data.session || !data.session.access_token) {
        showAuthError(_t('auth_err_server', 'Invalid response from server. Please try again.'));
        return;
    }
    _token = data.session.access_token;
    localStorage.setItem('meshctx-token', _token);
    _user = data.user;
    updateAuthUI();
    hideAuthModal();
    } catch(e) { btn.disabled = false; btn.textContent = _t('auth_signin_btn', 'Sign In'); showAuthError(_t('auth_err_network', 'Network or server error. Please try again.')); }
}

// ═══ OAuth (GitHub) ═══
async function signInWithOAuth(provider) {
    var sb = _getSupabase();
    if (!sb) { showAuthError(_t('auth_err_config', 'Auth config error. Please contact support.')); return; }

    var btn = document.getElementById('oauth-btn-' + provider);
    if (btn) { btn.disabled = true; }

    var { data, error } = await sb.auth.signInWithOAuth({
        provider: provider,
        options: { redirectTo: window.location.origin + '/' }
    });
    if (error) {
        showAuthError(_t('auth_err_oauth', error.message || 'OAuth sign-in failed'));
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
    if (!sb) { showAuthError(_t('auth_err_connection', 'Network error. Check your connection and try again.')); return; }
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

// ═══ Password Recovery (from email reset link) ═══
function checkRecoveryStrength() {
    _checkPwdStrength('recovery-password', 'pwd-strength-bar-recovery', '.pwd-strength-wrap');
}

function showRecoveryForm() {
    var modal = document.getElementById('auth-modal');
    if (!modal) return;
    document.querySelectorAll('.auth-tab-content').forEach(function(el) { el.style.display = 'none'; });
    document.querySelectorAll('.auth-tab-btn').forEach(function(el) { el.classList.remove('active'); });
    var tab = document.getElementById('auth-tab-recovery');
    if (tab) tab.style.display = 'block';
    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';
    clearAuthError();
}

async function confirmPasswordReset() {
    var sb = _getSupabase();
    if (!sb) { showAuthError(_t('auth_err_connection', 'Network error.')); return; }
    if (!_token) { showAuthError(_t('auth_err_session', 'Session expired. Please request a new reset link.')); return; }

    var pw = document.getElementById('recovery-password').value;
    var pw2 = document.getElementById('recovery-password2').value;
    if (!pw) { showAuthError(_t('auth_err_empty', 'Please enter a new password.')); return; }
    if (!isPasswordStrong(pw)) { showAuthError(_t('auth_err_pwd_weak', 'Password must be 8+ chars with uppercase, lowercase, and number.')); return; }
    if (pw !== pw2) { showAuthError(_t('auth_err_pwd_match', 'Passwords do not match.')); return; }

    var btn = document.getElementById('recovery-btn');
    btn.disabled = true;
    btn.textContent = _t('auth_btn_updating', 'Updating…');

    try {
        var { data, error } = await sb.auth.updateUser({ password: pw });
        btn.disabled = false;
        btn.textContent = _t('auth_recovery_btn', 'Update Password');
        if (error) { showAuthError(error.message); return; }

        // Success — clear recovery params, show signin
        history.replaceState(null, '', window.location.pathname);
        _token = null; _user = null;
        localStorage.removeItem('meshctx-token');
        localStorage.removeItem('meshctx-refresh-token');
        hideAuthModal();
        alert('Password updated successfully! You can now sign in with your new password.');
        showAuthModal('signin');
    } catch(e) {
        btn.disabled = false;
        btn.textContent = _t('auth_recovery_btn', 'Update Password');
        showAuthError(_t('auth_err_network', 'Network error. Please try again.'));
    }
}

function handleRecoveryFlow() {
    // Parse URL hash for Supabase recovery params
    var hash = window.location.hash.substring(1); // remove '#'
    if (!hash) return false;
    var params = {};
    hash.split('&').forEach(function(pair) {
        var kv = pair.split('=');
        params[decodeURIComponent(kv[0])] = decodeURIComponent(kv[1] || '');
    });
    if (params.type !== 'recovery' || !params.access_token) return false;

    var sb = _getSupabase();
    if (!sb) return false;

    // Set the recovery session, then show the password form
    sb.auth.setSession({
        access_token: params.access_token,
        refresh_token: params.refresh_token || ''
    }).then(function(result) {
        if (result.error) {
            alert('This password reset link is invalid or has expired. Please request a new one.');
            history.replaceState(null, '', window.location.pathname);
            return;
        }
        showRecoveryForm();
    });
    return true;
}

// ═══ Change Password ═══
async function changePassword(newPassword) {
    var sb = _getSupabase();
    if (!sb || !_user) return { error: { message: _t('auth_err_login_required', 'Please sign in first.') } };
    if (!newPassword || newPassword.length < 8) return { error: { message: _t('auth_err_pwd_weak', 'Password must be 8+ chars with uppercase, lowercase, and number.') } };
    var { data, error } = await sb.auth.updateUser({ password: newPassword });
    return { data: data, error: error };
}

// ═══ Sign Out ═══
async function signOut() {
    var sb = _getSupabase();
    if (!sb) { showAuthError(_t('auth_err_connection', 'Network error. Check your connection and try again.')); return; }
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
            userName.textContent = meta.full_name || meta.display_name || meta.user_name || _user.email || 'User';
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
    if (!sb || !_user) return { error: _t('auth_err_login_required', 'Please sign in first.') };

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

// addEmail — reserved for future multi-email support (requires custom table)
// Supabase GoTrue does not support secondary emails via REST API
async function addEmail(newEmail) {
    var sb = _getSupabase();
    if (!sb) return { error: _t('auth_err_login_required', 'Please sign in first.') };
    return await sb.auth.updateUser({ email: newEmail });
}

// ═══ Init ═══
async function initAuth() {
    // Check for password recovery flow first (from email reset link)
    if (handleRecoveryFlow()) return;

    var sb = _getSupabase();
    var authBtn = document.getElementById('auth-btn');
    if (!sb) {
        if (authBtn) authBtn.style.display = 'inline-flex';
        return;
    }

    try {
        var { data } = await sb.auth.getSession();
        if (data && data.session && data.session.user) { _user = data.session.user; }
    } catch(e) { /* session not found — expected on first visit */ }

    updateAuthUI();

    sb.auth.onAuthStateChange(function(event, session) {
        _user = session ? session.user : null;
        updateAuthUI();
        if (event === 'SIGNED_IN') {
            hideAuthModal();
            /* auth state restored */
        }
    });
}

// Keyboard shortcut
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') hideAuthModal();
});

document.addEventListener('DOMContentLoaded', initAuth);

// Also handle recovery when hash changes (e.g. user clicks reset link in email)
window.addEventListener('hashchange', function() {
    if (location.hash.includes('type=recovery')) handleRecoveryFlow();
});
