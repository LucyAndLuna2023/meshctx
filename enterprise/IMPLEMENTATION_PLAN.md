# MeshCtx Enterprise — 三阶段实施计划

> 从开源项目 → 企业级多 Agent 平台
> 996 行代码，3 个阶段，12 个月

---

## 📊 概览

```
 阶段 1 (本周)        阶段 2 (本月)        阶段 3 (下季度)
 ──────────────────  ──────────────────  ──────────────────
 PyPI 发布           Agent 集群           K8s 生产就绪
 Docker 镜像         角色模板 6x          SSO 集成
 pip install         Registry 注册        可观测性栈
 docker pull         A2A 消息总线         成本中心
                     HITL 人工审批        合规审计
```

---

## 🚀 阶段 1: 产品化发布 (本周)

### 目标
任何人可以通过 `pip install meshctx` 或 `docker pull` 安装

### 文件
| 文件 | 行数 | 说明 |
|------|------|------|
| `publish_pypi.sh` | 60 | PyPI 发布: 版本自增 → lint → test → build → upload |
| `publish_docker.sh` | 34 | Docker 发布: build → verify → push |

### 检查清单
- [ ] `publish_pypi.sh patch` → pip install meshctx
- [ ] `publish_docker.sh latest` → docker pull meshctx/meshctx
- [ ] GitHub Release v3.115.31
- [ ] README badge: PyPI + Docker Hub

### 成功标准
```bash
pip install meshctx && meshctx --version  # 3.115.31
docker run --rm meshctx/meshctx --version # 3.115.31
```

---

## 🔧 阶段 2: 企业集群 (本月)

### 目标
6 个专业 Agent 协同工作，人工审批集成

### 文件
| 文件 | 行数 | 说明 |
|------|------|------|
| `agent_roles.yaml` | 152 | 6 角色: 法务/财务/HR/DevOps/安全/研发 |
| `agent_registry.py` | 190 | 注册/发现/路由/心跳 |
| `a2a_protocol.py` | 242 | Agent-to-Agent 消息总线 (Redis Pub/Sub + HTTP) |
| `human_in_loop.py` | 207 | 人工审批 (Slack + 飞书 + Web) |

### 架构
```
                    ┌──────────────┐
                    │ AgentRegistry│ (Redis/etcd)
                    └──────┬───────┘
           ┌───────────────┼───────────────┐
    ┌──────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐
    │ 法务 Agent   │ │ DevOps Agent │ │ 安全 Agent  │ ...
    └──────┬──────┘ └──────┬──────┘ └──────┬──────┘
           │               │               │
           └───────────────┼───────────────┘
                    ┌──────▼───────┐
                    │   A2A Bus    │ (Redis Pub/Sub)
                    └──────┬───────┘
                    ┌──────▼───────┐
                    │    HITL      │ (Slack/飞书/Web)
                    └──────────────┘
```

### 检查清单
- [ ] 6 角色 Agent 启动成功
- [ ] Registry 注册/发现正常
- [ ] A2A 消息收发 (延迟 < 100ms)
- [ ] HITL: Slack 审批 → Agent 继续执行
- [ ] 单元测试覆盖 > 80%

---

## 🏭 阶段 3: 生产就绪 (下季度)

### 目标
K8s 一键部署，企业 SSO，全链路可观测

### 文件
| 文件 | 说明 |
|------|------|
| `helm_chart/` | K8s Helm Chart (Deployment + Service + Ingress + ConfigMap) |

### 检查清单
- [ ] `helm install meshctx ./helm_chart` → 6 Agent Pod running
- [ ] HPA 自动扩缩容 (CPU > 70% → +replicas)
- [ ] Ingress + TLS 终止
- [ ] SSO: OIDC/SAML/LDAP 集成
- [ ] Prometheus metrics + Grafana dashboard
- [ ] 成本中心: API 调用按 Agent 分账
- [ ] SOC2/GDPR 合规审计

### K8s 部署
```bash
# 一键部署
helm repo add meshctx https://helm.meshctx.com
helm install meshctx meshctx/meshctx \
  --set ingress.hosts[0].host=meshctx.example.com \
  --set sso.enabled=true \
  --set sso.issuerUrl=https://sso.example.com
```

---

## 📈 里程碑

```
 Q3 2026: 阶段 1 ✅ — PyPI + Docker
 Q4 2026: 阶段 2 ✅ — 6 Agent 集群 + HITL
 Q1 2027: 阶段 3 ✅ — K8s 生产就绪 + SSO
```

---

## 🔗 相关仓库

- [meshctx](https://github.com/LucyAndLuna2023/meshctx) — 核心代码
- [helm-charts](https://github.com/LucyAndLuna2023/helm-charts) — K8s Charts
