#!/usr/bin/env python3
"""Fix all src/core modules to satisfy test imports."""
import os, re, ast, sys, textwrap
from pathlib import Path

ROOT = Path("/home/administrator/meshctx-public")
SRC_CORE = ROOT / "src" / "core"

# Track which modules we need to recreate after batch edits
TO_IMPLEMENT = {}

def get_test_imports(test_file):
    """Parse a test file and extract all src.core imports with their names."""
    content = test_file.read_text()
    imports = {}  # module -> set of names
    
    for match in re.finditer(
        r'from\s+(src\.core\.\S+)\s+import\s*\(([^)]+)\)',
        content
    ):
        mod = match.group(1)
        names_block = match.group(2)
        names = {n.strip() for n in names_block.replace('\n',' ').split(',') if n.strip()}
        names = {n.split(' as ')[0].strip() for n in names}  # handle 'CircuitBreaker as CB'
        if mod not in imports:
            imports[mod] = set()
        imports[mod] |= names
    
    for match in re.finditer(
        r'from\s+(src\.core\.\S+)\s+import\s+(.+?)$',
        content,
        re.MULTILINE
    ):
        mod = match.group(1)
        names_str = match.group(2).strip()
        if '(' in names_str:
            continue  # already handled
        names = {n.strip().split(' as ')[0].strip() for n in names_str.split(',') if n.strip()}
        if mod not in imports:
            imports[mod] = set()
        imports[mod] |= names
    
    return imports

def get_missing_imports(test_file):
    """Check which imports from a test file are missing from the module."""
    content = test_file.read_text()
    missing = {}
    
    for match in re.finditer(
        r'from\s+(src\.core\.\S+)\s+import\s*\(([^)]+)\)',
        content
    ):
        mod = match.group(1)
        names_block = match.group(2)
        names = {n.strip().split(' as ')[0].strip() for n in names_block.replace('\n',' ').split(',') if n.strip()}
        missing_from_mod = check_module_missing(mod, names)
        if missing_from_mod:
            missing[mod] = missing_from_mod
    
    for match in re.finditer(
        r'from\s+(src\.core\.\S+)\s+import\s+(.+?)$',
        content,
        re.MULTILINE
    ):
        mod = match.group(1)
        names_str = match.group(2).strip()
        if '(' in names_str:
            continue
        names = {n.strip().split(' as ')[0].strip() for n in names_str.split(',') if n.strip()}
        missing_from_mod = check_module_missing(mod, names)
        if missing_from_mod:
            if mod not in missing:
                missing[mod] = set()
            missing[mod] |= missing_from_mod
    
    return missing

def check_module_missing(mod_path, names):
    """Check which names are missing from a module."""
    mod_name = mod_path.split('.')[-1]
    py_file = SRC_CORE / f"{mod_name}.py"
    
    if not py_file.exists():
        return names  # all missing
    
    # Try to import the module and check
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(mod_name, str(py_file))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return {n for n in names if not hasattr(mod, n)}
    except Exception as e:
        # Module can't be loaded - probably has its own issues
        return names

def extract_class_api(test_file, class_name):
    """Extract the expected API of a class from test usage."""
    content = test_file.read_text()
    methods = set()
    attributes = set()
    
    # Find method calls: obj.method_name(
    for match in re.finditer(rf'{class_name}\.(\w+)\s*\(', content):
        methods.add(match.group(1))
    
    # Find attribute accesses: obj.attr =
    for match in re.finditer(rf'{class_name}\.(\w+)\s*=', content):
        attributes.add(match.group(1))
    
    return methods, attributes

def generate_class_from_tests(test_file, class_name):
    """Generate a dataclass based on how tests construct it."""
    content = test_file.read_text()
    params = {}
    defaults = {}
    
    # Find constructor calls: ClassName(param=value, ...)
    pattern = rf'{class_name}\s*\(([^)]*(?:\([^)]*\)[^)]*)*)\)'
    for match in re.finditer(pattern, content, re.DOTALL):
        args_str = match.group(1)
        # Simple parsing
        for arg in args_str.split(','):
            arg = arg.strip()
            if '=' in arg:
                k, v = arg.split('=', 1)
                k = k.strip()
                v = v.strip()
                if k not in params:
                    params[k] = []
                params[k].append(v)
            else:
                if arg:
                    if arg not in params:
                        params[arg] = []
    
    # Determine types from values
    fields = []
    for k, vals in params.items():
        typ = 'str'
        default_val = None
        for v in vals:
            v = v.strip().strip("'").strip('"')
            if v in ('True', 'False'):
                typ = 'bool'
                default_val = False
            elif v.replace('.','',1).replace('-','',1).isdigit() and '.' in v:
                typ = 'float'
                default_val = 0.0
            elif v.replace('-','',1).isdigit():
                typ = 'int'
                default_val = 0
            elif v.startswith('['):
                typ = 'list'
                default_val = 'field(default_factory=list)'
            elif v.startswith('{'):
                typ = 'dict'
                default_val = 'field(default_factory=dict)'
            else:
                typ = 'str'
                default_val = '""'
        if default_val:
            fields.append(f"    {k}: {typ} = {default_val}")
        else:
            fields.append(f"    {k}: {typ}")
    
    return fields

def scan_all():
    """Scan all test files with errors and collect what needs to be fixed."""
    error_files = [
        "tests/test_agent_swarm.py",
        "tests/test_agent_swarm_v2.py",
        "tests/test_api_gateway.py",
        "tests/test_auto_tuner.py",
        "tests/test_backup_vault.py",
        "tests/test_deep_research.py",
        "tests/test_deep_research_v2.py",
        "tests/test_email_engine.py",
        "tests/test_feedback_loop.py",
        "tests/test_goal_checker.py",
        "tests/test_hooks_engine.py",
        "tests/test_knowledge_graph_v2.py",
        "tests/test_mcp_standardizer.py",
        "tests/test_memory_compactor.py",
        "tests/test_memory_persistence.py",
        "tests/test_multi_modal.py",
        "tests/test_notification_hub.py",
        "tests/test_plugin_market.py",
        "tests/test_prompt_optimizer.py",
        "tests/test_pwa_builder.py",
        "tests/test_rate_limiter.py",
        "tests/test_security_scanner.py",
        "tests/test_summon_engine.py",
        "tests/test_task_queue_v2.py",
        "tests/test_v16_multi_agent.py",
        "tests/test_v16_online_learning.py",
        "tests/test_v34_progressive_ctx.py",
        "tests/test_v35_session_resume.py",
        "tests/test_v37_credential_pool.py",
        "tests/test_v37_desktop_agent.py",
        "tests/test_v39_gateway.py",
        "tests/test_v39_jepa_router.py",
        "tests/test_v40_evolution_tracker.py",
        "tests/test_v40_human_memory.py",
        "tests/test_v41_autonomous.py",
        "tests/test_v42_hooks.py",
        "tests/test_v42_teams.py",
        "tests/test_v44_diff_preview.py",
        "tests/test_v46_sdb.py",
        "tests/test_v47_self_modify.py",
        "tests/test_v48_brain_validator.py",
        "tests/test_v48_subconscious.py",
        "tests/test_v49_autonomous_action.py",
        "tests/test_v49_gateway_llm.py",
        "tests/test_v50_feedback_loop.py",
        "tests/test_v50_unified_loop.py",
        "tests/test_v51_attractor.py",
        "tests/test_v51_knowledge_sync.py",
        "tests/test_v52_intent_predict.py",
        "tests/test_v53_self_opt_router.py",
        "tests/test_v54_breakthrough_memory.py",
        "tests/test_v54_security_audit.py",
        "tests/test_v55_plugin_hotreload.py",
        "tests/test_v55_precompute.py",
        "tests/test_v56_distributed_mesh.py",
        "tests/test_v56_tuner.py",
        "tests/test_v57_benchmark.py",
        "tests/test_v57_deploy_engine.py",
        "tests/test_v58_benchmark.py",
        "tests/test_v59_evolution.py",
        "tests/test_v59_health.py",
        "tests/test_v61_knowledge_graph.py",
        "tests/test_v62_context_compression.py",
        "tests/test_v63_smart_permissions.py",
        "tests/test_v64_desktop_agent.py",
        "tests/test_v65_agent_governance.py",
        "tests/test_v66_jepa_router.py",
        "tests/test_v67_model_compare.py",
        "tests/test_v68_auto_healer.py",
        "tests/test_v69_perf_optimizer.py",
        "tests/test_v71_session_resume.py",
        "tests/test_v72_shield.py",
        "tests/test_v72_task_queue.py",
        "tests/test_v73_llm_quality.py",
        "tests/test_v74_sandbox.py",
        "tests/test_v75_knowledge_transfer.py",
        "tests/test_v76_cache.py",
    ]
    
    all_missing = {}
    for tf in error_files:
        path = ROOT / tf
        if not path.exists():
            continue
        missing = get_missing_imports(path)
        for mod, names in missing.items():
            if mod not in all_missing:
                all_missing[mod] = set()
            all_missing[mod] |= names
    
    return all_missing

if __name__ == "__main__":
    all_missing = scan_all()
    for mod, names in sorted(all_missing.items()):
        print(f"{mod}: {sorted(names)}")
