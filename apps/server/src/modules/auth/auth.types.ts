export type AuthRole = "platform_admin";
export type LoginAttemptOutcome = "SUCCESS" | "FAILURE" | "THROTTLED";

export interface AuthUserIdentityRecord {
  userId: string;
  username: string;
  displayName: string;
  roles: [AuthRole];
  disabled: boolean;
}

export interface AuthUserRecord extends AuthUserIdentityRecord {
  passwordHash: string;
}

export interface NewAuthSession {
  sessionDigest: string;
  userId: string;
  createdAt: string;
  lastSeenAt: string;
  idleExpiresAt: string;
  absoluteExpiresAt: string;
}

export interface AuthSessionRecord extends AuthUserIdentityRecord {
  sessionDigest: string;
  createdAt: string;
  lastSeenAt: string;
  idleExpiresAt: string;
  absoluteExpiresAt: string;
  revokedAt: string | null;
}

export interface LoginAttemptCounts {
  usernameFailures: number;
  globalFailures: number;
}

export interface AuthRepository {
  findUserByUsername(username: string): Promise<AuthUserRecord | null>;
  countRecentFailures(usernameDigest: string, since: string): Promise<LoginAttemptCounts>;
  recordLoginAttempt(
    usernameDigest: string,
    outcome: LoginAttemptOutcome,
    attemptedAt: string,
  ): Promise<void>;
  createSession(session: NewAuthSession): Promise<void>;
  findSession(sessionDigest: string): Promise<AuthSessionRecord | null>;
  touchSession(sessionDigest: string, lastSeenAt: string, idleExpiresAt: string): Promise<boolean>;
  revokeSession(sessionDigest: string, revokedAt?: string): Promise<void>;
}
