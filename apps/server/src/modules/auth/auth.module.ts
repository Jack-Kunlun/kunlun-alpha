import { Module } from "@nestjs/common";
import { APP_GUARD } from "@nestjs/core";
import { Pool } from "pg";
import { AuthController } from "./auth.controller";
import { loadAuthConfig, type AuthConfig } from "./auth.config";
import { AuthenticationGuard } from "./auth.guard";
import { AuthService } from "./auth.service";
import { AUTH_CONFIG, AUTH_PASSWORD_HASHER, AUTH_REPOSITORY } from "./auth.tokens";
import { ScryptPasswordHasher } from "./password";
import { PostgresAuthRepository } from "./postgres-auth.repository";

@Module({
  controllers: [AuthController],
  providers: [
    { provide: AUTH_CONFIG, useFactory: () => loadAuthConfig(process.env) },
    {
      provide: AUTH_REPOSITORY,
      inject: [AUTH_CONFIG],
      useFactory: (config: AuthConfig) =>
        new PostgresAuthRepository(new Pool({ connectionString: config.postgresDsn })),
    },
    { provide: AUTH_PASSWORD_HASHER, useFactory: () => new ScryptPasswordHasher() },
    AuthService,
    { provide: APP_GUARD, useClass: AuthenticationGuard },
  ],
  exports: [AuthService, AUTH_CONFIG],
})
export class AuthModule {}
