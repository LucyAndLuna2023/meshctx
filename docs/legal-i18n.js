// MeshCtx Legal Pages — i18n Loader
(function(){
var LANG_NAMES = {
    en:'English', zh:'中文', fr:'Français', de:'Deutsch',
    ja:'日本語', ko:'한국어', es:'Español', it:'Italiano', ar:'العربية'
};

function detectLang() {
    var stored = localStorage.getItem('meshctx-lang');
    if (stored && LANG_NAMES[stored]) return stored;
    var nav = (navigator.language || 'en').split('-')[0];
    return LANG_NAMES[nav] ? nav : 'en';
}

function render(data) {
    var lang = detectLang();
    var t = data[lang] || data['en'];
    document.documentElement.lang = lang;

    // Render all data-key elements
    var els = document.querySelectorAll('[data-key]');
    els.forEach(function(el) {
        var key = el.getAttribute('data-key');
        if (t[key]) {
            if (el.tagName === 'DIV') {
                el.innerHTML = t[key];
            } else {
                el.textContent = t[key];
            }
        }
    });

    // Language switcher
    var sw = document.getElementById('lang-switch');
    if (!sw) return;
    sw.innerHTML = '';
    Object.keys(LANG_NAMES).forEach(function(code) {
        var btn = document.createElement('button');
        btn.textContent = LANG_NAMES[code];
        if (code === lang) btn.classList.add('active');
        btn.onclick = function() {
            localStorage.setItem('meshctx-lang', code);
            render(data);
        };
        sw.appendChild(btn);
    });
}

// Load i18n JSON
var xhr = new XMLHttpRequest();
xhr.open('GET', 'legal-i18n.json', true);
xhr.onload = function() {
    if (xhr.status === 200) {
        try { render(JSON.parse(xhr.responseText)); }
        catch(e) { console.error('legal-i18n parse error:', e); }
    }
};
xhr.send();
})();
