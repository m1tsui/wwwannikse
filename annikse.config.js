module.exports = {
  apps: [{
    name: "annikse",
    cwd: process.env.HOME + "/domeenid/www.oruvilla.ee/annikse",
    script: process.env.HOME + "/domeenid/www.oruvilla.ee/annikse/.venv/bin/uvicorn",
    args: "main:app --host 127.0.0.1 --port 8001",
    interpreter: process.env.HOME + "/domeenid/www.oruvilla.ee/annikse/.venv/bin/python3",
    max_memory_restart: "256M"
  }]
}