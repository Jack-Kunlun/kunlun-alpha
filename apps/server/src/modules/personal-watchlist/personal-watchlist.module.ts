import { Module } from "@nestjs/common";
import { Pool } from "pg";
import { PersonalWatchlistController } from "./personal-watchlist.controller";
import { PersonalWatchlistRepository } from "./personal-watchlist.repository";
@Module({
  controllers: [PersonalWatchlistController],
  providers: [
    {
      provide: PersonalWatchlistRepository,
      useFactory: () => {
        const connectionString = process.env.AUTH_POSTGRES_DSN ?? process.env.KUNLUN_POSTGRES_DSN;
        if (!connectionString) throw new Error("personal watchlist requires PostgreSQL");
        return new PersonalWatchlistRepository(new Pool({ connectionString }));
      },
    },
  ],
})
export class PersonalWatchlistModule {}
