const express = require('express');
const axios = require('axios');

const app = express();

// GET with a path param and an axios egress to the inventory service.
app.get('/orders/:id', async (req, res) => {
  const inv = await axios.get('http://inventory/items/' + req.params.id);
  res.json(inv.data);
});

// POST with a named handler and a bare fetch egress to the payments service.
app.post('/orders', function createOrder(req, res) {
  fetch('http://payments/charge', { method: 'POST' });
  res.status(201).end();
});

// A DB/ORM call must NOT be read as HTTP egress (parity with the Python over-match guard).
app.get('/health', (req, res) => {
  db.query('SELECT 1');
  res.send('ok');
});

app.listen(3000);
