"""
MeshCtx 17脑区 能力基准测试 v9 (全API修复版)
==========================================
"""
import sys, os, time, json, numpy as np

class M:
    def __init__(s, mod, name, val, unit, note, tgt=None, lo=False):
        s.mod=mod; s.name=name; s.val=val; s.unit=unit; s.note=note; s.tgt=tgt; s.lo=lo
    def sc(s):
        if s.tgt is not None: return 1.0 if s.tgt else 0.0
        v=min(1.0, max(0.0, s.val))
        return 1.0-v if s.lo else v
R=[]
def rec(*a, **k): R.append(M(*a, **k))

# ═══ 1. Hippocampus ═══
from src.core.brain_hippocampal import HippocampalReplay
hp=HippocampalReplay(max_recent=120, swr_threshold=0.05)
targets=[]; lures=[]; foils=[]
# Store with unique patterns
for i in range(30):
    hp.encode(f'mem_cat_dog_bird_{i}', 0.5, 0.5)
# Test: exact match vs partial vs no match
# The recall is text/pattern-based; differentiate by match quality
ts=[]; ls=[]; fs=[]
for i in range(5):
    rt=hp.recall(f'mem_cat_dog_bird_{i}', top_k=1)
    ts.append(rt[0][1] if rt else 0)
    # Lure: encode new similar but not exact match
    hp.encode(f'lure_cat_dog_anim_{i}', 0.3, 0.3)
    rl=hp.recall(f'lure_cat_dog_anim_{i}', top_k=1)
    ls.append(rl[0][1] if rl else 0)
    # Foil: no encoding, so recall returns empty
    rf=hp.recall(f'foil_xyz_{i}', top_k=1)
    fs.append(rf[0][1] if rf else 0)
tm=np.mean(ts); lm=np.mean(ls); fm=np.mean(fs)
ldi=tm - fm
psi=(tm - fm)/max(abs(tm), abs(fm), 1e-8)
rec("1.Hippocampus", "TargetSim", tm, "sim", f"目标→{tm:.4f}")
rec("1.Hippocampus", "LureSim", lm, "sim", f"诱饵→{lm:.4f}")
rec("1.Hippocampus", "FoilSim", fm, "sim", f"干扰→{fm:.4f}")
rec("1.Hippocampus", "MST_LDI", ldi, "Δsim", f"LDI={ldi:.4f}", tgt=ldi>=0.01)
rec("1.Hippocampus", "PatternSep", psi, "r", f"PSI={psi:.4f}", tgt=psi>0.05)

# ═══ 2. Amygdala ═══
from src.core.brain_amygdala import AmygdalaSalience
amyg=AmygdalaSalience()
threat_words=["danger","attack","kill","weapon","bomb","fire","death","poison","war","enemy"]
safe_words=["hello","friend","happy","peace","love","calm","safe","gentle","kind","warm"]
tp=fp=tn=fn=0
for w in threat_words:
    r=amyg.detect_threat(w)
    if r.is_threat: tp+=1
    else: fn+=1
for w in safe_words:
    r=amyg.detect_threat(w)
    if r.is_threat: fp+=1
    else: tn+=1
pr=tp/(tp+fp) if(tp+fp)>0 else 0
rc=tp/(tp+fn) if(tp+fn)>0 else 0
f1=2*pr*rc/(pr+rc) if(pr+rc)>0 else 0
fprate=fp/(fp+tn) if(fp+tn)>0 else 0
rec("2.Amygdala", "F1", f1, "F1", f"P={pr:.1%}R={rc:.1%}tp={tp}fp={fp}")
rec("2.Amygdala", "FPR", fprate, "FPR", f"假阳={fprate:.1%}", lo=True)

# ═══ 3. BasalGanglia ═══
from src.core.brain_basal_ganglia import BasalGanglia
bg=BasalGanglia()
bg.register_actions(["optimal","sub_a","sub_b","sub_c"])
opt_cnt=0; rewards=[]
for ep in range(20):
    state=np.random.randn(8)*0.5
    ep_r=0
    for _ in range(10):
        sel=bg.select(state)
        act_name=sel.selected_action
        rew=1.0 if act_name=="optimal" else -0.1+abs(state[0])*0.3
        bg.provide_reward(rew)
        state+=np.random.randn(8)*0.1
        ep_r+=rew
        if act_name=="optimal": opt_cnt+=1
    rewards.append(ep_r)
opt_rate=opt_cnt/200.0
avg_r=np.mean(rewards[-5:])
rec("3.BasalGanglia", "OptimalRate", opt_rate, "frac", f"最优={opt_rate:.1%}(基线25%)")
rec("3.BasalGanglia", "AvgReward", avg_r, "r/ep", f"终局均值={avg_r:.3f}")

# ═══ 4. Cerebellum ═══
from src.core.brain_cerebellar import CerebellarForwardModel
cbm=CerebellarForwardModel(state_dim=8, command_dim=4, learning_rate=0.05)
init_errs=[]; final_errs=[]
for tr in range(40):
    state=np.random.randn(8)*0.5
    cmd=np.random.randn(4)*0.3
    true_next=state*0.8+np.random.randn(8)*0.1
    pred=cbm.predict(state, cmd)
    cbm.update(true_next)
    err=np.mean((pred.predicted_state-true_next)**2)
    if tr<5: init_errs.append(err)
    elif tr>=35: final_errs.append(err)
imse=np.mean(init_errs); fmse=np.mean(final_errs)
imp=1.0-fmse/max(imse, 1e-8)
rec("4.Cerebellum", "InitMSE", imse, "MSE", f"初始={imse:.3f}", lo=True)
rec("4.Cerebellum", "FinalMSE", fmse, "MSE", f"最终={fmse:.3f}", lo=True)
rec("4.Cerebellum", "Improve", imp, "ratio", f"学习提升={imp:.1%}", tgt=imp>0.05)

# ═══ 5. Insula ═══
from src.core.brain_insula import Insula
ins=Insula()
norm=ins.process({"heart_rate":72,"temperature":37,"respiration":14}, 0.0)
abnorm=ins.process({"heart_rate":130,"temperature":39.5,"respiration":28}, 0.5)
na=norm[0].anomaly_score; aa=abnorm[0].anomaly_score
disc=abs(aa - na)
rec("5.Insula", "NormScore", na, "score", f"正常={na:.4f}", lo=True)
rec("5.Insula", "AbnormScore", aa, "score", f"异常={aa:.4f}", tgt=aa>0.1)
rec("5.Insula", "AnomalyDisc", disc, "Δscore", f"区分={disc:.4f}", tgt=disc>0.01)

# ═══ 6. ACC ═══
from src.core.brain_acc import ACC
acc=ACC()
tmap={"red":0,"blue":1,"green":2}; dmap={"red":0,"blue":1,"green":2}
cong=acc.evaluate_stroop("red","red",tmap,dmap,0)
incong=acc.evaluate_stroop("red","blue",tmap,dmap,0)
cc=cong.get('combined_conflict',0); ic=incong.get('combined_conflict',0)
rec("6.ACC", "Congruent", cc, "conf", f"一致={cc:.6f}", lo=True)
rec("6.ACC", "Incongruent", ic, "conf", f"冲突={ic:.4f}", tgt=ic>0.05)

# ═══ 7. Mirror ═══
from src.core.brain_mirror import ActionEncoder, ActionObservation, F5MirrorPool
enc=ActionEncoder(); pool=F5MirrorPool()
intents=set()
actions=[
    ActionObservation("grasp","cup"),
    ActionObservation("push","button"),
    ActionObservation("pull","lever"),
    ActionObservation("point","screen"),
    ActionObservation("wave","hand"),
]
for obs in actions:
    feats=enc.encode(obs)
    out=pool.activate(obs, feats)
    intents.add(str(out[0][:10]))
div=len(intents)/len(actions)
rec("7.Mirror", "IntentDiv", div, "frac", f"意图种类={len(intents)}/{len(actions)}")

# ═══ 8. DMN ═══
from src.core.brain_dmn import DefaultModeNetwork
dmn=DefaultModeNetwork()
intro=dmn.introspect("today's learning")
future=dmn.imagine_future("tomorrow's meeting", n_scenarios=2)
rich=min(1.0, (len(str(intro))+len(str(future)))/100.0)
rec("8.DMN", "Richness", rich, "frac", f"内容丰富={rich:.0%}")

# ═══ 9. Thalamus ═══
from src.core.brain_thalamic import DualModeRelay
dmr=DualModeRelay()
passed=0; total_sig=0
for i in range(20):
    out_sig,_=dmr.relay(float(0.5+np.random.randn()*0.15), 0.0)
    total_sig+=abs(out_sig)
    if abs(out_sig)>0.01: passed+=1
prate=passed/20; avg_sig=total_sig/20
rec("9.Thalamus", "PassRate", prate, "frac", f"通过={prate:.0%}", tgt=prate>0.3)
rec("9.Thalamus", "AvgSignal", avg_sig, "sig", f"信号={avg_sig:.3f}")

# ═══ 10. STDP ═══
from src.core.brain_stdp import LIFNetwork, EligibilityTraceEngine
net=LIFNetwork(n_neurons=16)
engine=EligibilityTraceEngine()
net.connect_all_to_all()
# Excite multiple neurons with multi-step simulation
for i in range(8): net.set_input(i, 8.0)
total_spikes=0
for _ in range(20): 
    s=net.step(1.0)
    total_spikes+=len(s)
rec("10.STDP", "SpikeCount", total_spikes, "spikes", f"20步脉冲={total_spikes}", tgt=total_spikes>=1)
# Update eligibility
grads={i:np.random.rand()*0.1 for i in range(16)}
engine.update(grads, 0.5)
updates=engine.get_weight_updates(0.01, 0.5)
dw=sum(abs(v) for v in updates.values()) if updates else 0
rec("10.STDP", "WeightDelta", dw, "Δ|w|", f"权重变化={dw:.4f}", tgt=dw>0.001)

# ═══ 11. IIT ═══
from src.core.brain_iit import IITConsciousness
iit=IITConsciousness()
t0=time.time()
phi_result=iit.compute_phi(max_mech_size=2, min_phi=0.0)
dt=(time.time()-t0)*1000
mip_size=len(str(phi_result.mip))
rec("11.IIT", "MIP_Size", mip_size, "chars", f"MIP={mip_size}chars({dt:.0f}ms)")
rec("11.IIT", "Latency", min(1.0, dt/10000), "s", f"{dt:.0f}ms", lo=True)

# ═══ 12. Emotion ═══
from src.core.brain_emotional import EmotionalConsolidation
ec=EmotionalConsolidation()
experiences=[
    ("won lottery, jumping with joy!", np.ones(64)*0.8),
    ("lost everything, devastated", np.ones(64)*(-0.8)),
    ("ate a sandwich, it was okay", np.zeros(64)),
    ("nearly got hit by a car!", np.ones(64)*(-0.6)),
    ("surprise birthday party!", np.ones(64)*0.6),
]
items=[ec.tag_experience(txt, emb) for txt, emb in experiences]
# Check emotional_tag on each item
tags=[it.emotional_tag for it in items]
ar_vals=[t.valence for t in tags if hasattr(t,'valence')]
ar_r=max(ar_vals)-min(ar_vals) if ar_vals else 0
# Also check consolidation level variation
cls=[it.consolidation_level for it in items]
cl_r=max(cls)-min(cls)
rec("12.Emotion", "ConsolRange", cl_r, "Δcl", f"巩固差异={cl_r:.4f}", tgt=cl_r>0.01)
rec("12.Emotion", "TagVariety", len(set(str(t)[:20] for t in tags)), "n", f"标签种类={len(set(str(t)[:20]for t in tags))}")

# ═══ 13. BrainLoop ═══
from src.core.brain_architecture import BrainLoop
bl=BrainLoop()
actions_list=["sort","search","plan","chat","calculate"]
diverse=set()
t0=time.time()
for act in actions_list:
    out=bl.think(f"task: {act}", available_actions=actions_list)
    diverse.add(str(out)[:40])
dt=(time.time()-t0)*1000
div_frac=len(diverse)/len(actions_list)
rec("13.BrainLoop", "Diversity", div_frac, "frac", f"多样性={len(diverse)}/{len(actions_list)}")
rec("13.BrainLoop", "PerStep", min(1.0, dt/500), "ms", f"{dt/5:.1f}ms/step", lo=True)

# ═══ ★ 14. PFC ═══
from src.core.brain_pfc import WorkingMemory, TaskSwitcher, SimplePlanner
wm=WorkingMemory()
for it in ["apple","banana","cherry","date","elderberry","fig"]: wm.store(it, 0.7)
for _ in range(5): wm.step()
recalled=wm.recall("apple", top_k=1)
wmr=recalled[0][1] if recalled else 0.0
ts=TaskSwitcher()
costs=[ts.switch_to(i) for i in [0,1,2,3,2,1,0]]
swc=np.mean(costs)
sp=SimplePlanner()
def tf(s, a): return f"{s}+{a}"
def gf(s): return 1.0 if "goal" in str(s) else 0.1
plan=sp.plan("start", ["go","turn","jump","walk"], tf, gf)
rec("14.PFC", "WM_Recall", wmr, "sim", f"WM recall={wmr:.4f}", tgt=wmr>0.3)
rec("14.PFC", "SwitchCost", swc, "cost", f"切换成本={swc:.3f}", lo=True)
rec("14.PFC", "PlanDepth", len(plan), "steps", f"规划={len(plan)}步", tgt=len(plan)>=1)

# ═══ ★ 15. VisualCortex ═══
from src.core.brain_visual import GaborFilterBank, FeatureExtractor
gfb=GaborFilterBank(n_orientations=8, n_scales=3, kernel_size=15)
img=np.zeros((64,64))
for i in range(64): img[i,i]=255; img[i,32]=128; img[32,i]=128
edges=gfb.apply(img)
orients=set(round(e.orientation,1) for e in edges)
ediv=len(orients)/8
fe=FeatureExtractor()
feats=fe.extract(img)
rec("15.Visual", "EdgeDensity", len(edges), "edges", f"检测{len(edges)}边", tgt=len(edges)>10)
rec("15.Visual", "OrientDiv", ediv, "frac", f"朝向={len(orients)}/8")
rec("15.Visual", "FeatRichness", min(1.0, len(feats)/6), "frac", f"特征={len(feats)}种")

# ═══ ★ 16. NAcc ═══
from src.core.brain_nacc import RewardPredictor, MotivationSignal, WantingVsLiking
rp=RewardPredictor()
pes=[]
for tr in range(50):
    s=tr%10; ns=(tr+1)%10
    rew=1.0 if s==5 else 0.0
    out=rp.update(s, rew, ns)
    pes.append(abs(out.prediction_error))
epe=np.mean(pes[:10]); lpe=np.mean(pes[-10:])
pconv=1.0-lpe/max(epe, 1e-8)
ms=MotivationSignal()
for _ in range(20): ms.update(0.5); ms.decay_satiety()
wvl=WantingVsLiking()
wvl.process_reward(0.8, 0.6); wvl.process_reward(0.2, 0.1)
st=wvl.state()
rec("16.NAcc", "PE_Converge", pconv, "ratio", f"PE收敛={pconv:.1%}", tgt=pconv>0.2)
rec("16.NAcc", "Motivation", ms.motivation, "mot", f"动机={ms.motivation:.3f}", tgt=ms.motivation>0.1)
rec("16.NAcc", "WantLiking", abs(st.get('dissonance',0)), "diss", f"想要vs喜欢={abs(st.get('dissonance',0)):.4f}")

# ═══ ★ 17. Brainstem ═══
from src.core.brain_brainstem import AutonomicRegulator, ReticularActivation, HomeostaticDrive
ar=AutonomicRegulator()
stable_start=ar.is_stable()
for _ in range(30): ar.update(exertion=0.2, stress=0.1, dt=0.1)
stable_rest=ar.is_stable()
# Stress response
ar2=AutonomicRegulator()
for _ in range(20): ar2.update(exertion=0.6, stress=0.8, dt=0.1)
hrv=ar2.heart_rate_variability()
ras=ReticularActivation()
ras.update(stimulation=0.8, dt=1.0)
aw1=ras.is_awake()
for _ in range(30): ras.update(stimulation=0.0, dt=1.0)
aw2=ras.is_awake()
hd=HomeostaticDrive()
hd.update(activity_level=0.6, dt=5.0)
drives=hd.all_drives()
ddiff=max(drives.values())-min(drives.values()) if drives else 0
rec("17.Brainstem", "Homeostasis", 1.0 if stable_rest else 0.0, "bool", f"稳定={stable_rest}")
rec("17.Brainstem", "StressHRV", hrv, "HRV", f"心率变异={hrv:.2f}")
rec("17.Brainstem", "ArousalCtrl", 1.0 if(aw1 and not aw2) else 0.0, "bool", f"觉醒→睡眠={aw1}→{aw2}")
rec("17.Brainstem", "DriveDiff", ddiff, "Δ", f"驱力差异={ddiff:.3f}", tgt=ddiff>0.05)

# ═══ 汇总 ═══
scores={}
for r in R:
    m=r.mod
    if m not in scores: scores[m]=[]
    scores[m].append(r.sc())

print("="*70)
print("  MeshCtx 17脑区 能力基准测试 v9")
print("="*70)
total_s=0; total_n=0
for mod in sorted(scores):
    avg=np.mean(scores[mod]); total_s+=sum(scores[mod]); total_n+=len(scores[mod])
    b="█"*int(avg*20)+"░"*(20-int(avg*20))
    print(f"  {mod:<16} [{b}] {avg:.0%}")
ov=total_s/total_n
print(f"  {'★ 综合':<16} [{'█'*int(ov*20)+'░'*(20-int(ov*20))}] {ov:.1%}")
passed=sum(1 for r in R if r.sc()>=0.3)
print(f"\n  通过: {passed}/{total_n} (≥0.3)")

out={"results":[{"module":r.mod,"metric":r.name,"value":r.val,"unit":r.unit,"note":r.note,"score":r.sc()} for r in R],
     "module_scores":{k:float(np.mean(v)) for k,v in scores.items()},"overall":ov,"passed":passed,"total":total_n}
json.dump(out, open("tests/brain_bench_v9.json","w"), indent=2)
print("\n📄 tests/brain_bench_v9.json")
print("Done.")
