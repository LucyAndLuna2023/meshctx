const fs = require('fs');
const html = fs.readFileSync('/home/administrator/meshctx-local/docs/index.html', 'utf8');

const match = html.match(/const L = (\{.*?\n\});/s);
if (!match) {
    console.log('L object not found');
    process.exit(1);
}

try {
    eval('var L = ' + match[1]);
    console.log('JS L parse: OK');
    console.log('Languages: ' + Object.keys(L).join(', '));
    
    for (const lang of Object.keys(L)) {
        console.log('  ' + lang + ': ' + Object.keys(L[lang]).length + ' keys');
    }
    
    const keyMatches = html.match(/data-lang-key="(\w+)"/g);
    const uniqueKeys = [...new Set(keyMatches.map(k => k.match(/"(\w+)"/)[1]))];
    console.log('HTML keys: ' + uniqueKeys.length);
    
    let errors = 0;
    for (const lang of Object.keys(L)) {
        for (const key of uniqueKeys) {
            if (!L[lang][key]) {
                console.log('  MISSING: ' + lang + '.' + key);
                errors++;
            }
        }
    }
    
    if (errors === 0) {
        console.log('All translations complete! SwitchLang should work.');
    } else {
        console.log(errors + ' missing translations found!');
        process.exit(1);
    }
} catch(e) {
    console.log('JS parse ERROR: ' + e.message);
    process.exit(1);
}
