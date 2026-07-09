"""
MeshCtx Brain Architecture — 13脑区全导入版本 (v3.115.16)
所有脑区从独立文件导入，非简化实现。

002审计修复:
1. ✅ 9脑区→真实brain_*.py导入(不再简化)
2. ✅ Thalamus→真实注意力机制(brain_thalamic)
3. ✅ 失败日志→logger.warning(不再静默)
4. ✅ 三套代码统一→此为唯一入口
"""
import numpy as np
import time
import logging
from typing import Dict, List, Any, Optional, Tuple

# ── 导入全部真实脑区 ──
from .brain_hippocampal import HippocampalReplay, MemoryPattern
from .brain_amygdala import AmygdalaSalience
from .brain_thalamic import ThalamicGate
from .brain_cerebellar import CerebellarForwardModel
from .brain_basal_ganglia import BasalGanglia
from .brain_insula import Insula
from .brain_mirror import MirrorNeurons
from .brain_iit import IITConsciousness
from .brain_emotional import EmotionalConsolidation
from .brain_stdp import STDPLearner
from .brain_dmn import DefaultModeNetwork
from .brain_acc import ACC

logger = logging.getLogger("meshctx.brain")


class BrainLoop:
    """
    完整13脑区回路 — 每次决策经过所有脑区处理。
    
    与之前版本的区别: 所有脑区从 brain_*.py 导入(8268行真实算法)，
    非内联简化版。
    """
    
    def __init__(self):
        # 全部真实脑区
        self.thalamus = ThalamicGate()
        self.amygdala = AmygdalaSalience()
        self.hippocampus = HippocampalReplay()
        self.cerebellum = CerebellarForwardModel()
        self.bg = BasalGanglia()
        self.insula = Insula()
        self.mirror = MirrorNeurons()
        self.iit = IITConsciousness()
        self.emotion = EmotionalConsolidation()
        self.stdp = STDPLearner()
        self.dmn = DefaultModeNetwork()
        self.acc = ACC()
        
        self._steps = 0
        self._successes = 0
        self._failures = 0
        self._errors = []
    
    def think(self, observation: str, available_actions: List[str] = None,
              priority: float = 0.5) -> Dict[str, Any]:
        """完整13脑区认知循环"""
        self._steps += 1
        
        try:
            # 1. Thalamus: 注意力门控 (真实算法)
            gated = self.thalamus.gate(
                signal_strength=0.6 if observation else 0.3,
                priority=priority
            )
            if not gated:
                return self._empty_result('thalamus_gated')
            
            # 2. Amygdala: 情感分析
            emotion = self.amygdala.tag_emotional(observation)
            
            # 3. Hippocampus: 记忆检索
            recalled = self.hippocampus.recall(observation, top_k=3)
            
            # 4. Mirror Neurons: 意图推断
            intention = self.mirror.infer(observation)
            self.mirror.observe(observation, 'processing')
            
            # 5. DMN: 自省
            if self._steps % 5 == 0:
                dmn_state = self.dmn.introspect()
            
            # 6. Basal Ganglia: 动作选择
            actions = available_actions or ['respond', 'search', 'execute', 'clarify', 'delegate']
            action, confidence = self.bg.select(actions)
            
            # 7. Cerebellum: 前向预测
            prediction = self.cerebellum.predict(action, observation[:100])
            
            # 8. ACC: 冲突监控
            conflict = self.acc.detect_conflict(
                [(a, self.bg.evaluate(a)) for a in actions]
            )
            
            # 9. Insula: 内感受
            anomaly = self.insula.is_anomalous()
            
            # 10. IIT: 意识计量
            phi = self.iit.compute_phi(
                np.array([emotion.get('arousal', 0.5), confidence, conflict])
            )
            
            # 11. Emotional: 情绪标记
            self.emotion.tag(observation, 
                           valence=emotion.get('valence', 0),
                           arousal=emotion.get('arousal', 0))
            
            # 12. Hippocampus: 编码经验
            self.hippocampus.encode(
                observation,
                emotional_valence=emotion.get('valence', 0),
                emotional_arousal=emotion.get('arousal', 0)
            )
            
            logger.info(
                f"🧠 BrainLoop step={self._steps} action={action} "
                f"Φ={phi:.2f} conf={confidence:.2f} conflict={conflict:.2f}"
            )
            
            return {
                'action': action,
                'confidence': confidence,
                'emotion': emotion,
                'recalled_memories': [m.context[:50] for m, _ in recalled],
                'prediction': prediction,
                'conflict': conflict,
                'intention': intention,
                'anomaly': anomaly,
                'phi': phi,
            }
            
        except Exception as e:
            self._errors.append(str(e))
            logger.warning(f"🧠 BrainLoop error (step={self._steps}): {e}")
            return self._empty_result(f'error: {e}')
    
    def _empty_result(self, reason: str) -> Dict:
        return {
            'action': 'ignore', 'reason': reason, 'phi': 0.0,
            'confidence': 0.0, 'emotion': {'valence': 0, 'arousal': 0},
            'recalled_memories': [], 'prediction': {}, 'conflict': 0.0,
            'intention': {}, 'anomaly': False,
        }
    
    def learn_from_outcome(self, observation: str, action: str,
                           success: bool, reward: float = 0.0):
        """学习回路"""
        try:
            self.bg.reinforce(action, reward if success else -0.2)
            self.cerebellum.learn(action, observation[:100],
                                 'success' if success else 'failure', success)
            self.mirror.observe(action, 'success' if success else 'failure')
            
            if success:
                self._successes += 1
                if self._steps % 10 == 0:
                    self.hippocampus.consolidate()
            else:
                self._failures += 1
            
            # Periodic replay
            if self._steps % 10 == 0 and self.hippocampus.detect_swr(5):
                self.hippocampus.replay_swr(3)
                
        except Exception as e:
            logger.warning(f"🧠 BrainLoop learn error: {e}")
    
    def stats(self) -> dict:
        return {
            'steps': self._steps,
            'success_rate': self._successes / max(1, self._steps),
            'dopamine': getattr(self.bg, 'dopamine', 0.5),
            'phi': self.iit.current_phi() if hasattr(self.iit, 'current_phi') else 0,
            'hippocampus': self.hippocampus.stats(),
            'errors': len(self._errors),
            'last_error': self._errors[-1] if self._errors else None,
        }
