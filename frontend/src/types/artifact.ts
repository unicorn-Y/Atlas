export interface Artifact {
  id: string;
  runId: string;
  type: 'file' | 'report' | 'patch' | 'image';
  name: string;
  path?: string;
  summary: string;
  createdAt: string;
}
