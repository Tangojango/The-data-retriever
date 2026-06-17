import matplotlib.pyplot as plt
import numpy as np

import numpy as np
import pandas as pd

def calculate_least_squares_line(x, y):
    """
    Calculate the least squares regression line for the given data.
    
    Parameters:
    x (array-like): Independent variable values (time).
    y (array-like): Dependent variable values (data).
    
    Returns:
    slope (float): Slope of the regression line.
    intercept (float): Intercept of the regression line.
    line_values (array-like): y-values of the regression line for plotting.
    """
    # Ensure x is in the right format (e.g., seconds or minutes)
    x = np.array(x)
    y = np.array(y)
    
    # Calculate the slope (m) and intercept (c) using numpy's lstsq method
    A = np.vstack([x, np.ones(len(x))]).T
    m, c = np.linalg.lstsq(A, y, rcond=None)[0]
    
    # Generate the line values for plotting
    line_values = m * x + c
    
    return m, c, line_values

# Example usage:
# x = np.arange(0, 300, 2)  # e.g., 5 minutes of data with a 2-second interval
# y = np.random.normal(size=len(x))  # some noisy data
# slope, intercept, line_values = calculate_least_squares_line(x, y)

# Generate some example data
x = np.arange(0, 300, 2)  # e.g., 5 minutes of data with a 2-second interval
y = np.random.normal(size=len(x))  # some noisy data

# Calculate the least squares line
slope, intercept, line_values = calculate_least_squares_line(x, y)

# Plot the noisy data
plt.scatter(x, y, label='Noisy data')

# Plot the least squares regression line
plt.plot(x, line_values, color='red', label=f'Least squares line\nslope: {slope:.4f}, intercept: {intercept:.2f}')

# Add labels and legend
plt.xlabel('Time (seconds)')
plt.ylabel('Value')
plt.legend()
plt.title('Least Squares Regression Line')

# Show the plot
plt.show()
