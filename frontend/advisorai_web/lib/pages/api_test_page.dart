import 'package:flutter/material.dart';
import 'dart:convert';
import '../services/api_service.dart';

/// API Test Page
/// Demonstrates:
/// - HTTP requests to Flask API
/// - Async/await pattern
/// - JSON parsing and display
/// - Error handling
/// - Future and FutureBuilder usage
class ApiTestPage extends StatefulWidget {
  const ApiTestPage({Key? key}) : super(key: key);

  @override
  State<ApiTestPage> createState() => _ApiTestPageState();
}

class _ApiTestPageState extends State<ApiTestPage> {
  final ApiService _apiService = ApiService();

  // State variables
  String? _responseData;
  bool _isLoading = false;
  String? _errorMessage;
  DateTime? _lastRequestTime;

  /// Make request to Flask /api/health endpoint
  Future<void> _testApiHealth() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
      _responseData = null;
      _lastRequestTime = DateTime.now();
    });

    try {
      // Call API service to get health status
      final response = await _apiService.getHealth();

      setState(() {
        _responseData = const JsonEncoder.withIndent('  ').convert(response);
        _isLoading = false;
      });
    } catch (e) {
      setState(() {
        _errorMessage = e.toString();
        _isLoading = false;
      });
    }
  }

  /// Test generic API endpoint
  Future<void> _testCustomEndpoint(String endpoint) async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
      _responseData = null;
      _lastRequestTime = DateTime.now();
    });

    try {
      final response = await _apiService.get(endpoint);

      setState(() {
        _responseData = const JsonEncoder.withIndent('  ').convert(response);
        _isLoading = false;
      });
    } catch (e) {
      setState(() {
        _errorMessage = e.toString();
        _isLoading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('API Test')),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // API Configuration Info
            _ApiConfigCard(apiService: _apiService),
            const SizedBox(height: 24),

            // Test Controls
            _TestControlsCard(
              onTestHealth: _testApiHealth,
              onTestCustom: _testCustomEndpoint,
              isLoading: _isLoading,
            ),
            const SizedBox(height: 24),

            // Response Display
            _ResponseCard(
              responseData: _responseData,
              errorMessage: _errorMessage,
              isLoading: _isLoading,
              lastRequestTime: _lastRequestTime,
            ),
          ],
        ),
      ),
    );
  }
}

/// Widget: API Configuration Information
class _ApiConfigCard extends StatelessWidget {
  final ApiService apiService;

  const _ApiConfigCard({required this.apiService});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  Icons.settings,
                  color: Theme.of(context).colorScheme.primary,
                ),
                const SizedBox(width: 8),
                Text(
                  'API Configuration',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.bold,
                      ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            _ConfigRow(label: 'Base URL', value: apiService.baseUrl),
            _ConfigRow(
              label: 'Timeout',
              value: '${apiService.timeoutSeconds}s',
            ),
          ],
        ),
      ),
    );
  }
}

class _ConfigRow extends StatelessWidget {
  final String label;
  final String value;

  const _ConfigRow({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 100,
            child: Text(
              '$label:',
              style: TextStyle(
                fontWeight: FontWeight.w500,
                color: Colors.grey[700],
              ),
            ),
          ),
          Expanded(
            child: SelectableText(
              value,
              style: const TextStyle(fontFamily: 'monospace'),
            ),
          ),
        ],
      ),
    );
  }
}

/// Widget: Test Controls
class _TestControlsCard extends StatelessWidget {
  final VoidCallback onTestHealth;
  final Function(String) onTestCustom;
  final bool isLoading;

  const _TestControlsCard({
    required this.onTestHealth,
    required this.onTestCustom,
    required this.isLoading,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  Icons.play_arrow,
                  color: Theme.of(context).colorScheme.primary,
                ),
                const SizedBox(width: 8),
                Text(
                  'Test Endpoints',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.bold,
                      ),
                ),
              ],
            ),
            const SizedBox(height: 16),

            // Health Check Button
            FilledButton.icon(
              onPressed: isLoading ? null : onTestHealth,
              icon: const Icon(Icons.health_and_safety),
              label: const Text('Test /api/health'),
            ),
            const SizedBox(height: 12),

            // Additional test buttons
            OutlinedButton.icon(
              onPressed: isLoading ? null : () => onTestCustom('/api/courses'),
              icon: const Icon(Icons.book),
              label: const Text('Test /api/courses'),
            ),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: isLoading ? null : () => onTestCustom('/api/students'),
              icon: const Icon(Icons.person),
              label: const Text('Test /api/students'),
            ),
          ],
        ),
      ),
    );
  }
}

/// Widget: Response Display
class _ResponseCard extends StatelessWidget {
  final String? responseData;
  final String? errorMessage;
  final bool isLoading;
  final DateTime? lastRequestTime;

  const _ResponseCard({
    required this.responseData,
    required this.errorMessage,
    required this.isLoading,
    required this.lastRequestTime,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  Icons.data_object,
                  color: Theme.of(context).colorScheme.primary,
                ),
                const SizedBox(width: 8),
                Text(
                  'Response',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.bold,
                      ),
                ),
                const Spacer(),
                if (lastRequestTime != null)
                  Text(
                    'Last request: ${_formatTime(lastRequestTime!)}',
                    style: Theme.of(
                      context,
                    ).textTheme.bodySmall?.copyWith(color: Colors.grey[600]),
                  ),
              ],
            ),
            const SizedBox(height: 16),

            // Loading state
            if (isLoading)
              const Center(
                child: Padding(
                  padding: EdgeInsets.all(32.0),
                  child: CircularProgressIndicator(),
                ),
              )
            // Error state
            else if (errorMessage != null)
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: Colors.red[50],
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: Colors.red[300]!),
                ),
                child: Row(
                  children: [
                    Icon(Icons.error_outline, color: Colors.red[700]),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'Error',
                            style: TextStyle(
                              fontWeight: FontWeight.bold,
                              color: Colors.red[900],
                            ),
                          ),
                          const SizedBox(height: 4),
                          SelectableText(
                            errorMessage!,
                            style: TextStyle(
                              fontFamily: 'monospace',
                              color: Colors.red[800],
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              )
            // Success state
            else if (responseData != null)
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: Colors.grey[50],
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: Colors.grey[300]!),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Icon(Icons.check_circle, color: Colors.green[700]),
                        const SizedBox(width: 8),
                        Text(
                          'Success',
                          style: TextStyle(
                            fontWeight: FontWeight.bold,
                            color: Colors.green[900],
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    SelectableText(
                      responseData!,
                      style: const TextStyle(
                        fontFamily: 'monospace',
                        fontSize: 13,
                      ),
                    ),
                  ],
                ),
              )
            // Initial state
            else
              Center(
                child: Padding(
                  padding: const EdgeInsets.all(32.0),
                  child: Column(
                    children: [
                      Icon(
                        Icons.cloud_outlined,
                        size: 64,
                        color: Colors.grey[400],
                      ),
                      const SizedBox(height: 16),
                      Text(
                        'No request sent yet',
                        style: TextStyle(color: Colors.grey[600]),
                      ),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  String _formatTime(DateTime time) {
    return '${time.hour.toString().padLeft(2, '0')}:'
        '${time.minute.toString().padLeft(2, '0')}:'
        '${time.second.toString().padLeft(2, '0')}';
  }
}
