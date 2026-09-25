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
        ATLAS_API_BASE: 'https://api.monkeyapi.net',
      },
    },
  ],
};
