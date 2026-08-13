import { Route, Routes } from 'react-router-dom'
import GraphExplorer from './views/GraphExplorer'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<GraphExplorer />} />
    </Routes>
  )
}
