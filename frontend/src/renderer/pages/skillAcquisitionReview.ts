export type SecurityGate = 'PASS' | 'WARN' | 'BLOCK';

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
