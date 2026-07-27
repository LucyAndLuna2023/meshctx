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

    var els = document.querySelectorAll('[data-key]');
    for (var i = 0; i < els.length; i++) {
        var el = els[i];
        var key = el.getAttribute('data-key');
        if (!t[key]) continue;
        // Use innerHTML for elements that may contain HTML (div, p, td, h2, h3, span)
        var tag = el.tagName;
        if (tag === 'DIV' || tag === 'P' || tag === 'H2' || tag === 'H3' || tag === 'SPAN' || tag === 'TD') {
            el.innerHTML = t[key];
        } else {
            el.textContent = t[key];
        }
    }

    var sw = document.getElementById('lang-switch');
    if (!sw) return;
    sw.innerHTML = '';
    var codes = Object.keys(LANG_NAMES);
    for (var j = 0; j < codes.length; j++) {
        var code = codes[j];
        var btn = document.createElement('button');
        btn.textContent = LANG_NAMES[code];
        if (code === lang) btn.classList.add('active');
        (function(c){ btn.onclick = function(){ localStorage.setItem('meshctx-lang', c); render(data); }; })(code);
        sw.appendChild(btn);
    }
}

// Load i18n JSON
var xhr = new XMLHttpRequest();
xhr.open('GET', 'legal-i18n.json', true);
xhr.onload = function() {
    if (xhr.status === 200) {
        try { render(JSON.parse(xhr.responseText)); }
        catch(e) { console.error('legal-i18n parse error:', e); }
    } else {
        console.error('legal-i18n.json HTTP', xhr.status);
    }
};
xhr.onerror = function() {
    console.error('legal-i18n.json failed to load');
};
xhr.send();
})();
