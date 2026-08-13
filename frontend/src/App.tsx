import { Route, Routes } from 'react-router-dom'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<p>Graph Explorer goes here.</p>} />
    </Routes>
  )
}
