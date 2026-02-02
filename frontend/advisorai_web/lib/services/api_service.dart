import 'dart:convert';
import 'package:http/http.dart' as http;

/// API Service Class
/// Handles all HTTP communication with the Flask REST API
///
/// Key Concepts Demonstrated:
/// - HTTP client usage
/// - Async/await for asynchronous operations
/// - JSON encoding/decoding
/// - Error handling
/// - Service layer pattern (separation of concerns)
class ApiService {
  // Base URL for the Flask API
  // NOTE: Update this to match your Flask server location
  // For local development: 'http://localhost:5000'
  // For DGX deployment: 'http://your-dgx-ip:5000'
  final String baseUrl;

  final int timeoutSeconds;

  /// Constructor with configurable base URL
  ApiService({
    this.baseUrl = 'http://127.0.0.1:5001',
    this.timeoutSeconds = 10,
  });

  /// Helper method to construct full URLs
  String _buildUrl(String endpoint) {
    // Remove leading slash if present to avoid double slashes
    final cleanEndpoint =
        endpoint.startsWith('/') ? endpoint.substring(1) : endpoint;
    return '$baseUrl/$cleanEndpoint';
  }

  /// Generic GET request handler
  ///
  /// Makes an HTTP GET request to the specified endpoint
  /// Returns parsed JSON as Map<String, dynamic>
  /// Throws exception on error
  ///
  /// Changed Map<String, dynamic> to dynamic to handle list cases
  Future<dynamic> get(String endpoint) async {
    final url = Uri.parse(_buildUrl(endpoint));

    try {
      print('Making GET request to: $url');

      // Make HTTP GET request with timeout
      final response = await http.get(url).timeout(
        Duration(seconds: timeoutSeconds),
        onTimeout: () {
          throw Exception('Request timeout after $timeoutSeconds seconds');
        },
      );

      print('Response status: ${response.statusCode}');
      print('Response body: ${response.body}');

      // Check HTTP status code
      if (response.statusCode == 200) {
        // Parse JSON response
        return jsonDecode(response.body);
      } else {
        // Handle error responses
        throw Exception(
          'HTTP ${response.statusCode}: ${response.reasonPhrase}\n${response.body}',
        );
      }
    } catch (e) {
      // Re-throw with more context
      throw Exception('API request failed: $e');
    }
  }

  /// Generic POST request handler
  ///
  /// Makes an HTTP POST request with JSON body
  /// Returns parsed JSON response
  Future<Map<String, dynamic>> post(
    String endpoint,
    Map<String, dynamic> data,
  ) async {
    final url = Uri.parse(_buildUrl(endpoint));

    try {
      print('Making POST request to: $url');
      print('Request body: ${jsonEncode(data)}');

      // Make HTTP POST request with JSON body
      final response = await http
          .post(
        url,
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode(data),
      )
          .timeout(
        Duration(seconds: timeoutSeconds),
        onTimeout: () {
          throw Exception('Request timeout after $timeoutSeconds seconds');
        },
      );

      print('Response status: ${response.statusCode}');
      print('Response body: ${response.body}');

      if (response.statusCode == 200 || response.statusCode == 201) {
        return jsonDecode(response.body) as Map<String, dynamic>;
      } else {
        throw Exception(
          'HTTP ${response.statusCode}: ${response.reasonPhrase}\n${response.body}',
        );
      }
    } catch (e) {
      throw Exception('API request failed: $e');
    }
  }

  // ========== Specific API Endpoints ==========

  /// GET /api/health - Health check endpoint
  /// Tests basic API connectivity
  Future<Map<String, dynamic>> getHealth() async {
    return await get('/api/health');
  }

  /// GET /api/courses - Fetch all courses
  /// Returns list of courses from the database
  Future<Map<String, dynamic>> getCourses() async {
    return await get('/api/courses');
  }

  /// GET /api/student/{id} - Fetch student information
  /// Returns student data by ID
  Future<Map<String, dynamic>> getStudent(int studentId) async {
    return await get('/api/students');
  }

  /// POST /api/chat - Send chat message to AdvisorAI
  /// Sends user message and receives AI response
  Future<Map<String, dynamic>> sendChatMessage(String message) async {
    return await post('/api/chat', {
      'message': message,
      'timestamp': DateTime.now().toIso8601String(),
    });
  }

  /// GET /api/recommendations/{student_id} - Get course recommendations
  /// Returns personalized course recommendations for student
  Future<Map<String, dynamic>> getRecommendations(int studentId) async {
    return await get('/api/recommendations/$studentId');
  }
}
