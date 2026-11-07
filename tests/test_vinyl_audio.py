import unittest
from vinyl_audio import SOURCE, SPEAKER, command, endpoints, linked


def node(number, name, kind, **props):
    return {'id': number, 'info': {'props': {'node.name': name, 'media.class': kind, **props}}}


class AudioRouteTests(unittest.TestCase):
    def test_routes_only_specific_usb_input_and_paired_speaker(self):
        source = node(10, SOURCE, 'Audio/Source')
        sink = node(20, 'bluez_output.ikea.2', 'Audio/Sink', **{'api.bluez5.address': SPEAKER})
        other = node(30, 'bluez_output.other', 'Audio/Sink', **{'api.bluez5.address': '00:00:00:00:00:00'})
        self.assertEqual(endpoints([other, source, sink]), (source, sink))
        self.assertEqual(endpoints([source, other]), (source, None))
        args = command(SOURCE, sink['info']['props']['node.name'])
        self.assertIn('bluez_output.ikea.2', args)
        self.assertTrue(all('node.dont-fallback=true' in args[i+1] for i in (args.index('-i'), args.index('-o'))))

    def test_reports_playing_only_when_both_graph_edges_are_active(self):
        source = node(10, SOURCE, 'Audio/Source')
        sink = node(20, 'speaker', 'Audio/Sink')
        nodes = [source, sink, node(30, 'cdspeler-vinyl.capture', 'Stream/Input/Audio'),
                 node(40, 'cdspeler-vinyl.playback', 'Stream/Output/Audio')]
        def edge(a,b,state='active'):
            return {'id': a+b, 'type':'PipeWire:Interface:Link',
                    'info':{'output-node-id':a,'input-node-id':b,'state':state}}
        self.assertFalse(linked(nodes, source, sink))
        self.assertFalse(linked(nodes+[edge(10,30)], source, sink))
        self.assertFalse(linked(nodes+[edge(10,30),edge(40,20,'paused')], source, sink))
        self.assertTrue(linked(nodes+[edge(10,30),edge(40,20)], source, sink))


if __name__ == '__main__':
    unittest.main()
