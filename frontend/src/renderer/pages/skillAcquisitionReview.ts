export type SecurityGate = 'PASS' | 'WARN' | 'BLOCK';

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
