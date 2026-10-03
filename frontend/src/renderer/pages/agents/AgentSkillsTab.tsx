import { useCallback, useEffect, useMemo, useState } from 'react';
import { FileDiff, LoaderCircle, RotateCcw, ShieldCheck, ShieldX } from 'lucide-react';
import { useAtlasStore } from '../../store/useAtlasStore';
import { agentSkillsApi, type AgentSkillRelation, type SkillProposal } from '../../services/persistentApi';
import { Button } from '../../ui/Button';
import { cn } from '../../ui/cn';
import type { PersistentAgentRecord } from '../../services/persistentApi';

const RELATION_LABEL: Record<string, string> = {
  adopted: '已采纳', learned: '学到', suggested: '建议', default_enabled: '默认开',
};
const STATUS_LABEL: Record<string, { text: string; className: string }> = {
  pending: { text: '待审查', className: 'bg-brand-soft text-fg' },
  applied: { text: '已应用', className: 'bg-ok-soft text-fg' },
  rejected: { text: '已拒绝', className: 'bg-danger-soft text-danger' },
  stale: { text: '已过期', className: 'bg-sunken text-fg-3' },
};

/** Skills：该 Agent 的技能开关（关系表）+ 技能提案审查（diff / approve / reject / rollback）。 */
export default function AgentSkillsTab({ apiBaseUrl, agent, onToast }: {
  apiBaseUrl: string; agent: PersistentAgentRecord; onToast: (text: string) => void;
}) {
  const globalSkills = useAtlasStore((state) => state.skills);
  const setAgentSkills = useAtlasStore((state) => state.setAgentSkills);
  const [relations, setRelations] = useState<AgentSkillRelation[]>([]);
  const [proposals, setProposals] = useState<SkillProposal[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const base = apiBaseUrl;
  const agentId = agent.id;

  const reload = useCallback(async () => {
    setLoading(true);
    const [skills, review] = await Promise.all([
      agentSkillsApi.list(base, agentId).catch(() => null),
      agentSkillsApi.proposals(base).catch(() => null),
    ]);
    if (skills) setRelations(skills.relations);
    if (review) setProposals(review.proposals);
    setLoading(false);
  }, [base, agentId]);
  useEffect(() => { void reload(); }, [reload]);

  // 开关列表 = 关系表 ∪ 全局技能目录（没进关系表的展示为可添加）。
  const rows = useMemo(() => {
    const known = new Map(relations.map((relation) => [relation.skill_name, relation]));
    const names = [...new Set([...relations.map((relation) => relation.skill_name), ...globalSkills.map((skill) => skill.name)])];
    return names.map((name) => ({ name, relation: known.get(name) }));
  }, [relations, globalSkills]);

  const toggle = async (name: string, enabled: boolean) => {
    setBusy(true);
    const existing = relations.find((relation) => relation.skill_name === name);
    const batch = existing
      ? relations.map((relation) => relation.skill_name === name ? { ...relation, enabled } : relation)
      : [...relations, { skill_name: name, enabled, relation: 'adopted' as const }];
    const ok = await setAgentSkills(agentId, batch.map(({ skill_name, enabled: on, relation, note }) => ({ skill_name, enabled: on, relation, note: note ?? undefined })));
    setBusy(false);
    onToast(ok ? `${name} 已${enabled ? '加入' : '移出'}这个 Agent` : '没有保存成功');
    if (ok) await reload();
  };

  const act = async (proposal: SkillProposal, action: 'approve' | 'reject' | 'rollback') => {
    setBusy(true);
    try {
      if (action === 'approve') await agentSkillsApi.approve(base, proposal.proposal_id);
      else if (action === 'reject') await agentSkillsApi.reject(base, proposal.proposal_id, window.prompt('拒绝理由（可留空）') ?? '');
      else await agentSkillsApi.rollback(base, proposal.proposal_id);
      onToast(action === 'approve' ? '提案已应用' : action === 'reject' ? '提案已拒绝' : '已回滚到应用前');
    } catch (error) { onToast(error instanceof Error ? error.message : String(error)); }
    setBusy(false);
    await reload();
  };

  if (loading) return <p className="flex items-center gap-2 py-6 text-[13px] text-fg-3"><LoaderCircle size={15} className="spin" />正在读取技能…</p>;

  return <div className="grid gap-6 lg:grid-cols-2 lg:items-start">
    <section aria-label="该 Agent 的技能">
      <h3 className="m-0 mb-2 text-[13.5px] font-semibold text-heading">这个 Agent 的技能</h3>
      <p className="m-0 mb-2.5 text-[12px] text-fg-3">技能本体只有一份（全局技能库），这里只是「这个 Agent 用哪些」的关系表。</p>
      <div className="grid gap-1.5">
        {rows.map(({ name, relation }) => <label key={name} className="flex items-center gap-2.5 rounded-xl bg-sunken px-3 py-2 text-[13px] shadow-[inset_0_0_0_1px_var(--line)]">
          <input type="checkbox" checked={Boolean(relation?.enabled)} disabled={busy} onChange={(event) => void toggle(name, event.target.checked)} />
          <span className="min-w-0 flex-1 truncate">{name}</span>
          {relation && <span className="rounded-full bg-surface px-2 py-0.5 text-[11px] text-fg-3">{RELATION_LABEL[relation.relation] ?? relation.relation}</span>}
        </label>)}
        {!rows.length && <p className="text-[12.5px] text-fg-3">技能库是空的。先去「技能」页装点技能。</p>}
      </div>
    </section>

    <section aria-label="技能提案审查">
      <h3 className="m-0 mb-2 flex items-center gap-1.5 text-[13.5px] font-semibold text-heading"><FileDiff size={15} />技能提案</h3>
      <p className="m-0 mb-2.5 text-[12px] text-fg-3">Agent 在干活时自己总结出的新技能。批准才会写入技能库，随时可以回滚。</p>
      <div className="grid gap-2.5">
        {proposals.map((proposal) => {
          const status = STATUS_LABEL[proposal.status] ?? { text: proposal.status, className: 'bg-sunken text-fg-3' };
          const writes = proposal.diff?.writes ?? {};
          const deletes = proposal.diff?.deletes ?? [];
          return <article key={proposal.proposal_id} className="rounded-xl bg-sunken p-3.5 shadow-[inset_0_0_0_1px_var(--line)]">
            <header className="mb-1.5 flex items-center gap-2">
              <b className="text-[13.5px] text-fg">{proposal.skill_name}</b>
              <span className={cn('rounded-full px-2 py-0.5 text-[11px]', status.className)}>{status.text}</span>
              {proposal.revision_hash && <span className="truncate font-mono text-[10.5px] text-fg-3">{proposal.revision_hash.slice(0, 10)}</span>}
              <span className="flex-1" />
              {proposal.status === 'pending' && <>
                <Button size="sm" variant="primary" disabled={busy} onClick={() => void act(proposal, 'approve')}><ShieldCheck />批准</Button>
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => void act(proposal, 'reject')}><ShieldX />拒绝</Button>
              </>}
              {proposal.status === 'applied' && <Button size="sm" variant="ghost" disabled={busy} onClick={() => void act(proposal, 'rollback')}><RotateCcw />回滚</Button>}
            </header>
            {proposal.goal && <p className="m-0 mb-1 text-[12.5px] leading-[1.6] text-fg-2">{proposal.goal}</p>}
            {proposal.evidence && <p className="m-0 mb-1.5 text-[12px] leading-[1.6] text-fg-3">依据：{proposal.evidence}</p>}
            {(Object.keys(writes).length > 0 || deletes.length > 0) && <details>
              <summary className="cursor-pointer select-none text-[12px] text-fg-3 hover:text-fg-2">改动明细（{Object.keys(writes).length} 写 / {deletes.length} 删）</summary>
              <div className="mt-2 grid gap-2">
                {Object.entries(writes).map(([path, content]) => <div key={path}>
                  <p className="m-0 mb-0.5 font-mono text-[11px] text-fg-3">{path}</p>
                  <pre className="m-0 max-h-44 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-surface p-2.5 font-mono text-[11.5px] leading-[1.6] text-fg-2 shadow-[inset_0_0_0_1px_var(--line)]">{content}</pre>
                </div>)}
                {deletes.map((path) => <p key={path} className="m-0 font-mono text-[11px] text-danger">删除 {path}</p>)}
              </div>
            </details>}
          </article>;
        })}
        {!proposals.length && <div className="empty py-8"><FileDiff size={20} /><b>没有待审查的提案</b>Agent 学到新技能时会出现在这里。</div>}
      </div>
    </section>
  </div>;
}
