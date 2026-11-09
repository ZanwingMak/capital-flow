"""真实SDK MORNING半日市编码回归；不连接行情。"""
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import research
import server


class HalfSessionTypesTests(unittest.TestCase):
    def test_morning_minutes_close_at_thirteen_in_us(self):
        root = Path.home() / '.hermes/cache/scratch/flowdesk-review/portfolio-tests'
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as directory, patch.object(research, 'DATA', Path(directory)):
            result = research.save_minutes('US', 'TEST', [
                {'capital_flow_item_time': '2024-07-03 13:00:00', 'big_in_flow': 100, 'super_in_flow': 0}
            ], {'2024-07-03': 'MORNING'})
        self.assertEqual(result[0]['closeTime'], '13:00')

    def date_at(self, time):
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.fromisoformat(time).astimezone(tz)
        context = Mock()
        with patch.object(server, 'datetime', Clock), patch.object(server, 'get_context', return_value=context), patch.object(
            server, 'provider_call', return_value=(0, [{'time': '2024-07-03', 'trade_date_type': 'MORNING'}])
        ):
            return server.intelligence_date('2024-07-03', 'US')

    def test_morning_completed_after_close_and_grace(self):
        self.assertEqual(self.date_at('2024-07-03T17:06:00+00:00'), '2024-07-03')

    def test_morning_not_completed_before_actual_close(self):
        with self.assertRaises(ValueError):
            self.date_at('2024-07-03T16:59:00+00:00')
