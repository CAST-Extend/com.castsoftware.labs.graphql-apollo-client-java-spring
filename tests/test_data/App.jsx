import { gql, useMutation, useQuery } from "@apollo/client";
import { useMemo, useState } from "react";

const GET_USERS = gql`
  query GetUsers {
    users { id name email }
  }
`;

const CREATE_USER = gql`
  mutation CreateUser($input: CreateUserInput!) {
    createUser(input: $input) { id name email }
  }
`;

export default function App() {
  const { data, loading, error, refetch } = useQuery(GET_USERS);
  const [createUser, { loading: creating }] = useMutation(CREATE_USER);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");

  const nextId = useMemo(() => {
    const ids = (data?.users ?? []).map(u => Number(u.id)).filter(n => Number.isFinite(n));
    return String((Math.max(0, ...ids) + 1));
  }, [data]);

  async function onCreate(e) {
    e.preventDefault();
    await createUser({ variables: { input: { id: nextId, name, email } } });
    setName("");
    setEmail("");
    await refetch();
  }

  return (
    <div style={{ fontFamily: "sans-serif", maxWidth: 720, margin: "40px auto" }}>
      <h1>Users (GraphQL)</h1>

      <form onSubmit={onCreate} style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name" required />
        <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Email" required />
        <button type="submit" disabled={creating}>
          {creating ? "Creating..." : "Create"}
        </button>
      </form>

      {loading && <div>Loading...</div>}
      {error && <pre>Error: {error.message}</pre>}

      <ul>
        {(data?.users ?? []).map((u) => (
          <li key={u.id}>
            <strong>{u.name}</strong> — {u.email} (id={u.id})
          </li>
        ))}
      </ul>

      <hr style={{ margin: "24px 0" }} />

      <h2>REST façade backed by GraphQL</h2>
      <p>Try: <code>http://localhost:8080/api/users/1</code></p>
    </div>
  );
}
