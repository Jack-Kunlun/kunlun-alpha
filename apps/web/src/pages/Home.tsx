import { env } from "../env";

export function Home() {
  return (
    <div>
      <h2 style={{ fontSize: 18, marginBottom: 8 }}>{env.TITLE}</h2>
      <p style={{ color: "var(--color-muted)" }}>
        观势 · 知势 · 策势
      </p>
    </div>
  );
}
