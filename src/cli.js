#!/usr/bin/env node
/**
 * meshctx CLI — Node.js wrapper for the meshctx Python agent.
 * Usage: npx meshctx [command]
 * 
 * Falls back to Python if available, otherwise provides
 * basic project management commands.
 */
'use strict';

const { spawn, execSync } = require('child_process');
const path = require('path');
const fs = require('fs');

const PKG_DIR = path.resolve(__dirname, '..');
const PY_PROJECT = PKG_DIR;

function pythonAvailable() {
  try {
    execSync('python3 --version', { stdio: 'ignore' });
    return 'python3';
  } catch {
    try {
      execSync('python --version', { stdio: 'ignore' });
      return 'python';
    } catch {
      return null;
    }
  }
}

function main() {
  const args = process.argv.slice(2);
  const cmd = args[0] || 'help';
  
  switch (cmd) {
    case 'start':
    case 'run': {
      const py = pythonAvailable();
      if (!py) { console.error('Python not found. Install Python 3.10+'); process.exit(1); }
      const child = spawn(py, ['-m', 'src.cli', 'start'], { 
        cwd: PY_PROJECT, 
        stdio: 'inherit' 
      });
      child.on('exit', code => process.exit(code));
      break;
    }
    case 'test': {
      const py = pythonAvailable();
      if (!py) { console.error('Python not found'); process.exit(1); }
      const child = spawn(py, ['-m', 'pytest', 'tests/', '-q'], { 
        cwd: PY_PROJECT, 
        stdio: 'inherit' 
      });
      child.on('exit', code => process.exit(code));
      break;
    }
    case 'version':
      console.log('meshctx v3.33.0');
      console.log('https://meshctx.com');
      console.log('GitHub: https://github.com/LucyAndLuna2023/meshctx');
      break;
    case 'install':
      console.log('Installing meshctx...');
      console.log('  curl -fsSL https://meshctx.com/install.sh | bash');
      console.log('  or: pip install meshctx');
      break;
    default:
      console.log('meshctx — Auditable Self-Adaptive Agent System');
      console.log('');
      console.log('Commands:');
      console.log('  meshctx start     Start the agent server');
      console.log('  meshctx test      Run test suite');
      console.log('  meshctx version   Show version info');
      console.log('  meshctx install   Show install instructions');
      console.log('');
      console.log('Docs: https://meshctx.com');
  }
}

main();
