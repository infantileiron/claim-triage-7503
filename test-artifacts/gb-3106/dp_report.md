# 差分隐私共享验证报告

日期：2026-11-20 ｜ 环境：Python 3.11.2（/tmp/dpenv，依赖版本同 backend/requirements.lock）+ SQLite（本地无 Docker，MySQL 路径代码未变）｜ 套件：`dp_test.py` 6 项，连跑 3 次全绿。

## 必验三项

| 场景 | 用例 | 结果 |
|---|---|---|
| 预算竞争 | `test_budget_contention`：真实 uvicorn 服务，8 线程并发 × ε=1.0 抢每版本固定总额 3.0 ε | 恰好 3 单 published、5 单 409「预算不足」；账本 spent=3.0 不超支；发布单 charged=1.0（结果可见即预算已扣）；预算不足单 charged=0/refunded=0（未扣费无需退还） |
| 空集 | `test_empty_set`：快照全为非节假日，筛选「仅节假日」命中 0 笔 | 仍走同一加噪路径发布 noisy_count/noisy_amount；响应不含原始计数/金额字段；固定种子下空集噪声确定非零且可复现；95% 误差界 = 尺度 × ln20 与口径一致 |
| 发布后响应丢失再重试 | `test_retry_after_response_loss` | 重试返回原噪声（逐位一致）、账本 spent 不变、单据仍 1 行；同号改预算/改筛选均 409；新单号改筛选正常受理并扣费 |

## 补充保障

- `test_concurrent_same_request_id`：6 线程同号同内容并发，全部 200、同一噪声、预算只扣一次（唯一约束 + 冲突重读）。
- `test_recovery_keeps_published`：受理中未发布单据恢复后退还并置失败；已发布结果不退款、结果保留。
- `test_guards`：viewer 提交 403、未完成训练 409、ε 超上限/筛选非法 422、版本不存在 404；额度与口径端点对只读账号开放。

## 端到端冒烟（真实服务，/tmp/dp_smoke.py）

首次发布 noisy_count=11.6274 / noisy_amount=13504.7059，扣 0.5 ε（余 2.5）；同载荷重试噪声逐位一致且额度不变；同号改 ε=0.6 返回 409；改筛选用新单号正常发布；列表展示受理/已发布/失败状态。

## 复现

```bash
python3 -m venv --without-pip /tmp/dpenv && /tmp/dpenv/bin/python get-pip.py   # 自举 pip
/tmp/dpenv/bin/pip install fastapi==0.115.6 uvicorn==0.34.0 SQLAlchemy==2.0.36 PyJWT==2.10.1 redis==5.2.1 httpx==0.28.1 pytest==8.3.4
cd test-artifacts/gb-3106 && /tmp/dpenv/bin/python -m pytest dp_test.py -v
```

Compose 全栈（MySQL/Redis/worker）下行为一致：账本原子扣减依赖单行条件 UPDATE，InnoDB 行锁串行化与 SQLite 单写者语义等价；建表与恢复扫描在 backend 启动 lifespan 执行。
