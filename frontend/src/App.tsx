import { Route, Routes } from 'react-router-dom'
import DocumentTable from './views/DocumentTable'
import GraphExplorer from './views/GraphExplorer'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<GraphExplorer />} />
      <Route path="/documents" element={<DocumentTable />} />
    </Routes>
  )
}
