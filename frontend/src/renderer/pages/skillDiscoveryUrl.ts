export interface SkillDiscoveryFilters {
  query: string;
  capability?: string;
  tool?: string;
  source?: string;
}

export function buildSkillDiscoveryUrl(baseUrl: string, filters: SkillDiscoveryFilters): string {
  const params = new URLSearchParams();
  if (filters.query.trim()) params.set('q', filters.query.trim());
  if (filters.capability) params.set('capability', filters.capability);
  if (filters.tool) params.set('tool', filters.tool);
  if (filters.source) params.set('source', filters.source);
  return `${baseUrl}/api/skills/discover?${params}`;
}

export function canActivateLocalSkill(
  skill: { source: string; status: string },
  lifecycle?: { state?: string; trust_state?: string },
): boolean {
  return skill.source === 'local' && skill.status === 'active'
    && lifecycle?.trust_state !== 'revoked' && lifecycle?.trust_state !== 'blocked'
    && lifecycle?.state !== 'quarantined' && lifecycle?.state !== 'removed';
}
