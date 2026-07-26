export interface LocalStorageArea {
  get(key: string): Promise<Record<string, unknown>>;
  set(items: Record<string, unknown>): Promise<void>;
  remove(key: string): Promise<void>;
}

export interface RegistrationClient {
  register(): Promise<{ token: string }>;
}

const TOKEN_KEY = "installationToken";

export class TokenStore {
  private inFlight: Promise<string> | undefined;

  constructor(
    private readonly storage: LocalStorageArea,
    private readonly registration: RegistrationClient,
  ) {}

  async getToken(): Promise<string> {
    const stored = await this.storage.get(TOKEN_KEY);
    if (typeof stored[TOKEN_KEY] === "string") return stored[TOKEN_KEY];
    this.inFlight ??= this.registration
      .register()
      .then(async ({ token }) => {
        await this.storage.set({ [TOKEN_KEY]: token });
        return token;
      })
      .finally(() => {
        this.inFlight = undefined;
      });
    return this.inFlight;
  }

  async clear(): Promise<void> {
    await this.storage.remove(TOKEN_KEY);
  }
}
