import { Link } from "react-router";

export function NotFound() {
  return (
    <div style={{ textAlign: "center", paddingTop: 80 }}>
      <h2 style={{ fontSize: 48, fontWeight: 700, color: "var(--color-muted)" }}>
        404
      </h2>
      <p style={{ marginTop: 12, color: "var(--color-muted)" }}>
        页面不存在
      </p>
      <Link
        to="/"
        style={{
          display: "inline-block",
          marginTop: 24,
          padding: "8px 20px",
          color: "#fff",
          background: "var(--color-primary)",
          borderRadius: 6,
          textDecoration: "none",
        }}
      >
        返回首页
      </Link>
    </div>
  );
}
