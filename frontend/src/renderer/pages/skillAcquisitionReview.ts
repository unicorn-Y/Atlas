export type SecurityGate = 'PASS' | 'WARN' | 'BLOCK';
export type CanonicalDependency = { kind: string; name: string; requested?: string | null };

type ApprovalResponse = { install_authorization?: string; detail?: string };

export function reviewGateState(result: SecurityGate, alreadyInstalled: boolean) {
  return {
    canInstall: result !== 'BLOCK' && !alreadyInstalled,
    requiresWarningConfirmation: result === 'WARN',
    result,
  };
}

export function remoteSkillLabel(installed: boolean): string {
  return installed ? '已安装' : 'Remote / Uninstalled';
}

export function formatCanonicalDependencies(dependencies: CanonicalDependency[]): string {
  return dependencies.map(({ kind, name, requested }) =>
    `${kind}:${name}${requested ? ` ${requested}` : ''}`,
  ).join(', ');
}

export function localPackageReviewState(state: 'new_skill' | 'exact_version_conflict' | 'update_candidate') {
  if (state === 'exact_version_conflict') {
    return { message: '同名同版本已存在；不会覆盖 Registry 或文件。', action: '已存在同版本', canProceed: false };
  }
  if (state === 'update_candidate') {
    return { message: '这是更新/降级候选，将进入现有 lifecycle 更新/降级审批。', action: '经现有 lifecycle 审批更新/降级', canProceed: true };
  }
  return { message: '新 Skill 导入候选。', action: '经 lifecycle 审批导入', canProceed: true };
}

export function lifecycleUpdateAction(currentVersion: string, incomingVersion: string): 'update' | 'downgrade' {
  const current = currentVersion.split('-')[0].split('.').map(Number);
  const incoming = incomingVersion.split('-')[0].split('.').map(Number);
  for (let index = 0; index < 3; index += 1) {
    const left = incoming[index] ?? 0;
    const right = current[index] ?? 0;
    if (left !== right) return left < right ? 'downgrade' : 'update';
  }
  return 'update';
}

export async function approveSkillInstallation(
  apiBaseUrl: string,
  acquisitionId: string,
  warningsConfirmed: boolean,
  fetcher: typeof fetch = fetch,
): Promise<Response> {
  const approvalResponse = await fetcher(`${apiBaseUrl}/api/skill-catalog/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ acquisition_id: acquisitionId, warnings_confirmed: warningsConfirmed }),
  });
  const approval = await approvalResponse.json() as ApprovalResponse;
  if (!approvalResponse.ok || !approval.install_authorization) {
    throw new Error(approval.detail ?? '无法记录明确批准');
  }
  return fetcher(`${apiBaseUrl}/api/skill-catalog/install`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ acquisition_id: acquisitionId, install_authorization: approval.install_authorization }),
  });
}
