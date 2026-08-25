export interface SeatKolWorkbenchQuery {
  asOf: string;
  entityType: "ALL" | "SEAT" | "KOL";
  reviewStatus: "ALL" | "UNREVIEWED" | "IN_REVIEW" | "APPROVED" | "REJECTED";
  query?: string;
}
