module.exports = {
  apps: [
    {
      name: 'atlas-backend',
      cwd: './core',
      script: 'python',
      args: '-m uvicorn atlas.server:app --host 0.0.0.0 --port 8765',
      interpreter: 'none',
      autorestart: true,
      watch: false,
      max_memory_restart: '500M',
      env: {
        // 与 config/atlas.toml 保持一致：反重力本地反代
        // ⚠ 注意：ATLAS_API_BASE / ATLAS_API_KEY 环境变量优先级最高，会覆盖 atlas.toml
        //   和 data/user-settings.json。改网关时这三处要同步。
        ATLAS_API_BASE: 'http://127.0.0.1:8045/v1',
        ATLAS_API_KEY: process.env.ATLAS_API_KEY ?? '',
      },
    },
  ],
};
