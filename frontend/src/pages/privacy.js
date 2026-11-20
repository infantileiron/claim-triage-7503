import {state} from '../stores/session.js';import {esc} from '../utils/html.js';import {badge} from '../components/common/status.js';import {field,select} from '../components/common/fields.js';
const FILTER={'all':'全部','yes':'仅节假日','no':'仅非节假日'};
export function render(){
 let p=state.dppolicy||{},done=state.trainings.filter(t=>t.state==='done');
 let sel=done.find(t=>t.id===state.selected?.id)||done[0]||null,ledger=sel?state.ledgers[sel.id]:null;
 let rows=state.dpqueries.map(q=>`<tr><td>${esc(q.request_id)}</td><td>#${q.training_id}</td><td>${esc(FILTER[q.holiday]||q.holiday)}</td><td>${q.epsilon}</td><td>${badge(q.state)}</td><td>${q.result?esc(q.result.noisy_count):'—'}</td><td>${q.result?esc(q.result.noisy_amount):'—'}</td><td>${q.result?esc(q.result.count_error95+' / '+q.result.amount_error95):'—'}</td><td>${esc(q.actor)}</td><td>${q.state==='failed'?esc(q.error):''}${q.state==='published'&&state.user.role!=='viewer'?` <button data-retry="${q.id}" data-rid="${esc(q.request_id)}" data-t="${q.training_id}" data-h="${esc(q.holiday)}" data-e="${q.epsilon}">重试</button>`:''}</td></tr>`).join('');
 return `<div class="split"><section class="panel"><h2>对外共享只发布加噪统计</h2><p class="notice">原始样本不出库。每次查询在已完成训练的冻结快照上按节假日筛选聚合，对数量与金额加 Laplace 噪声后发布；空集同样加噪。</p><h3>预先公开的口径</h3><div class=scroll><table><tbody>
 <tr><td>噪声机制</td><td>${esc(p.mechanism)}</td></tr>
 <tr><td>单票数量贡献上限</td><td>${esc(p.count_cap)}</td></tr>
 <tr><td>单票金额贡献上限</td><td>${esc(p.amount_cap)} 元（截断）</td></tr>
 <tr><td>预算分配</td><td>数量 ${(p.allocation?.count??.5)*100}% / 金额 ${(p.allocation?.amount??.5)*100}%</td></tr>
 <tr><td>误差依据</td><td>${esc(p.error_basis)}</td></tr>
 <tr><td>每版本总预算</td><td>${esc(p.version_budget)} ε（预先固定，各账号共用）</td></tr>
 <tr><td>单请求预算上限</td><td>${esc(p.max_epsilon)} ε</td></tr>
 <tr><td>空集口径</td><td>${esc(p.empty_set)}</td></tr></tbody></table></div>
 <h3>查询记录</h3><div class=scroll><table><thead><tr><th>单号</th><th>版本</th><th>筛选</th><th>预算ε</th><th>状态</th><th>噪声数量</th><th>噪声金额</th><th>95%误差界</th><th>发起人</th><th></th></tr></thead><tbody>${rows||'<tr><td>暂无查询。完成训练后在右侧发起。</td></tr>'}</tbody></table></div></section>
 <aside class="side"><h2>发起隐私查询</h2><form id="dpquery">${select('训练版本（已完成）','training_id',done.map(t=>[t.id,'#'+t.id+' '+t.name]))}${select('节假日筛选','holiday',[['all','全部'],['yes','仅节假日'],['no','仅非节假日']])}${field('本次预算 ε','epsilon','number','required min=0.05 max=1 step=0.05 value=0.5')}${field('查询单号','request_id','text','required minlength=4 maxlength=64 value="DP-'+Date.now()+'"')}<button class="primary">扣减预算并发布</button></form>
 ${ledger?`<h3>版本 #${sel.id} 额度</h3><p>总额 ${ledger.total} ε · 已扣 ${ledger.spent} ε · <strong>剩余 ${ledger.remaining} ε</strong></p>`:'<p>暂无已完成训练版本。</p>'}
 <p>同一单号重复提交返回原噪声、不重复扣费；单号相同但筛选或预算不同会被拒绝，须换新单号。结果可见即预算已扣；未发布的失败会退还，已发布不退还。</p></aside></div>`}
