const environmentVariableName = /^[A-Z][A-Z0-9_]*$/;

export function requireServerEnv(name: string): string {
  if (typeof window !== "undefined") {
    throw new Error("Server environment can only be read by server code.");
  }

  if (!environmentVariableName.test(name)) {
    throw new Error("Environment variable name is invalid.");
  }

  const value = process.env[name];

  if (!value || value.trim().length === 0) {
    throw new Error(`Missing required environment variable: ${name}`);
  }

  return value;
}
