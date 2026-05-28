import Link from "next/link";

export default function Nav() {
  return (
    <nav className="topnav">
      <Link href="/">Stations</Link>
      <Link href="/stats">Stats</Link>
      <Link href="/admin">Admin</Link>
    </nav>
  );
}
