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
