
# =============================================================================
#          File: firenzecard.py
#        Author: Io Flament
#       Created: July 2017
# Last Modified: October 2017
#   Description: Runs Exploratory Analysis of Firenzecard data
# =============================================================================

import sys
import pandas as pd
import numpy as np
import plotly
from plotly.graph_objs import *
import plotly.plotly as py
import plotly.graph_objs as go
sys.path.append('../src/')
#from IPython.core.debugger import Tracer

def get_national_museums(db_connection, export_to_csv, export_path):

    """
    Get national museum data from DB
    """

    df = pd.read_sql('select * from optourism.state_national_museum_visits', con=db_connection)

    if export_to_csv:
        df.to_csv(f"{export_path}_nationalmuseums_raw.csv", index=False)

    return df


def get_firenze_data(db_connection, export_to_csv, export_path):

    """
    Get FirenzeCard logs from DB
    """

    df = pd.read_sql('select * from optourism.firenze_card_logs', con=db_connection)

    if export_to_csv:
        df.to_csv(f"{export_path}_firenzedata_raw.csv", index=False)

    return df


def get_firenze_locations(db_connection, export_to_csv, export_path):

    """
    Get latitude and longitude fields from DB
    """

    df = pd.read_sql('select * from optourism.firenze_card_locations', con=db_connection)

    if export_to_csv:
        df.to_csv(f"{export_path}_firenzedata_locations.csv", index=False)

    return df


def extract_features(db_connection, path_firenzedata, path_firenzelocations_data, export_to_csv, export_path):

    """
    Feature extraction for FirenzeCard data

    Parameters
    ----------
    connection: postgres connection
    path_firenzedata: path to firenze logs data csv file
    path_firenzelocations_data: path to firenzelocations data csv file
    export_to_csv: boolean
    export_path: path to export data

    Returns
    -------

     1. Pandas dataframe with extracted features:
              - entry_is_adult: is the user an adult or not?
              - is_card_with_minors: is this a card used by minors?
              - time: time
              - date: date
              - hour: hour of day
              - day_of_week: day of the week
              - time_until_next_museum: how much time elapsed until next museum visit on a card?
              - duration_of_use: how many total days/hours was a card used?
              - (museum id column): per museum, a feature indicating whether a person was in that museum or not.
              column number is indicative of museum id.
              - number of museums visited so far
              - persons_per_card_per_museum
              - day of use
    """

    if path_firenzedata:
        df = pd.read_csv(path_firenzedata)
    else:
        df = get_firenze_data(db_connection, True, f"{export_path}_firenzedata_raw.csv")

    if path_firenzelocations_data:
        df_locations = pd.read_csv(path_firenzelocations_data)
    else:
        df_locations = get_firenze_locations(db_connection, True, f"{export_path}_firenzedata_locations.csv")

    df = pd.merge(df_locations, df, on=['museum_id', 'museum_name'], how='inner')

    df['entry_time'] = pd.to_datetime(df['entry_time'])
    df['time'] = pd.to_datetime(df['entry_time']).dt.time
    df['date'] = pd.to_datetime(df['entry_time']).dt.date
    df['hour'] = pd.to_datetime(df['entry_time']).dt.hour
    df['day_of_week'] = df['entry_time'].dt.dayofweek

    df = df.sort_values('entry_time', ascending=True)
    df['total_people'] = df['total_adults'] + df['minors']

    # todo remove overnights from time_since_previous museum - to only count on given days
    df['time_since_previous_museum'] = df.groupby('user_id')['entry_time'].diff()
    df['time_since_previous_museum'] = df['time_since_previous_museum'].apply(
        lambda x: pd.Timedelta(x) / pd.Timedelta('1 hour'))

    df = df.sort_values('entry_time', ascending=True)
    df['total_duration_card_use'] = df[df.user_id.notnull()].groupby(
        'user_id')['entry_time'].transform(lambda x: x.iat[-1] - x.iat[0])
    df['total_duration_card_use'] = df['total_duration_card_use'].apply(
        lambda x: pd.Timedelta(x) / pd.Timedelta('1 hour'))

    df['entry_is_adult'] = np.where(df['total_adults'] == 1, 1, 0)
    df['is_card_with_minors'] = np.where(df['minors'] == 1, 1, 0)

    entrances_per_card_per_museum = pd.DataFrame(df.groupby('user_id', as_index=True)['museum_id'].
                                                 value_counts().rename('entrances_per_card_per_museum'))

    df = pd.merge(entrances_per_card_per_museum.reset_index(), df, on=['user_id', 'museum_id'], how='inner')

    for n in range(1, df['museum_id'].nunique()):
        df['is_in_museum_' + str(n)] = np.where(df['museum_id'] == n, 1, 0)
    if export_to_csv:
        df.to_csv(f"{export_path}_firenzedata_feature_extracted.csv", index=False)

    return df


def interpolate_on_timedelta(df, groupby_object,timedelta, timedelta_range=,
                             count_column,timeunit, start_date, end_date):
    """
    Interpolate data on a given timedelta
    """

    df_interpolated = pd.DataFrame()

    if timedelta == 'day_of_week' or timedelta == 'hour':
        data = pd.DataFrame({timedelta: range(timedelta_range),
                             groupby_object: [id] * timedelta_range})

        df_interpolated = data.merge(df, how='outer', left_on=[timedelta, groupby_object],
                                     right_on=[timedelta, groupby_object])
        df_interpolated = df_interpolated.fillna(0)

    if timedelta == 'date':
        columns = [groupby_object, count_column]
        data = pd.DataFrame(0, np.arange(timedelta_range), columns)
        full_id_days = data.reindex(pd.MultiIndex.from_product([df[groupby_object].unique(),
                                                                pd.date_range(start_date, end_date,
                                                                              freq=timeunit)]), fill_value=0)
        full_id_days = full_id_days.reset_index()
        full_id_days.columns = ['drop this', timedelta, groupby_object, count_column]
        full_id_days = full_id_days.drop('drop this', 1)
        df_interpolated = pd.merge(full_id_days, df, how='right',
                                   on=[groupby_object, count_column, timedelta])

    return df_interpolated


def get_museum_entries_per_timedelta_and_plot(df, museum_list, me_names, timedelta, start_date, end_date,
                                              export_to_csv, export_path, plot):
    """
    Get museum timeseries for a given timedelta and plot
    """

    timedelta_range, timeunit = get_timedelta_range(df, timedelta, start_date, end_date)

    museum_dfs = {}
    plot_urls = {}

    museum_list.append('All Museums')

    for museum_name in museum_list[:]:

        if museum_name not in me_names:
            print('Wrong museum name! Please enter one of the following museums:')
            print(me_names)

        if museum_name != 'All Museums':
            df2 = df[df['short_name'].str.contains(museum_name)]
        else:
            df2 = df

        df2 = df2.groupby(['museum_id', 'short_name', timedelta], as_index=False)
        ['entrances_per_card_per_museum'].sum()
        df_interpolated = interpolate_on_timedelta(df2, 'museum_id', timedelta, timedelta_range,
                                                   'entrances_per_card_per_museum', timeunit)

        df_interpolated = df_interpolated.rename(columns={'entrances_per_card_per_museum': 'total_entries'})
        df_interpolated['total_entries'] = df_interpolated['total_entries'].fillna(0)

        if export_to_csv:
            df_interpolated.to_csv(f"{export_path} total_entries_{museum_name}_per_{timedelta}_.csv",
                                   index=False)

        df_interpolated = df_interpolated.groupby([timedelta, 'museum_id'], as_index=False)['total_entries'].sum()

        if plot:
            trace1 = go.Bar(
                x=df_interpolated[timedelta],
                y=df_interpolated['total_entries'])
            data = [trace1]
            layout = go.Layout(
                title=museum_name,
                xaxis=dict(
                    title=timedelta,
                    titlefont=dict(family='Courier New, monospace', size=18, color='#7f7f7f')),
                # rangeselector=dict(),
                # rangeslider=dict(),
                # type='date'),
                yaxis=dict(
                    title='Number of Museum Entries',
                    titlefont=dict(family='Courier New, monospace', size=18, color='#7f7f7f'))
            )

            fig = dict(data, layout)
            plot_url = py.plot(fig, filename=f"{museum_name}_{timedelta}_{start_date}_{end_date}",
                               sharing='private', auto_open=False)

            plot_urls[museum_name] = plot_url

        museum_dfs[museum_name] = df_interpolated

    return museum_dfs, plot_urls


def get_timedelta_range(df, tdr_timedelta, start_date, end_date):

    """
    Get timedelta range and unit for generating museum timeseries (called by get_museum_entries_per_timedelta_and_plot)
    """

    timedelta_options = ['day_of_week', 'hour', 'date']
    df = df[df['date'].isin(pd.date_range(start_date, end_date))]
    timeunit = pd.DataFrame()
    timedelta_range = pd.DataFrame()

    if tdr_timedelta not in timedelta_options:
        print("Wrong timedelta!")
        tdr_timedelta = input("Input a timedelta: 'hour', 'day_of_week' or 'date' ")
        timeunit, timedelta_range = get_timedelta_range(df, tdr_timedelta, start_date, end_date)

    if tdr_timedelta == 'day_of_week':
        timedelta_range = 7
        timeunit = []

    if tdr_timedelta == 'hour':
        timedelta_range = 24
        timeunit = []

    if tdr_timedelta == 'date':
        delta = pd.to_datetime(end_date) - pd.to_datetime(start_date)
        timedelta_range = delta.days
        timeunit = 'D'

    return timedelta_range, timeunit


def get_correlation_matrix(df, lst, corr_method, cm_timedelta, timedelta_subset, timedeltamin, timedeltamax,
                           below_threshold, above_threshold, export_to_csv, export_path):
    """
    Get correlation matrix of museum correlations and inverse correlations, for a given timedelta, at given thresholds
    """

    if timedelta_subset:
        df = df[(df[cm_timedelta] >= timedeltamin) & (df[cm_timedelta] <= timedeltamax)]

    df = df.pivot(cm_timedelta, columns='museum_id', values='total_entries')
    m = df.corr(corr_method).stack()
    corr_matrix = m[m.index.get_level_values(0) != m.index.get_level_values(1)]

    high = pd.DataFrame(corr_matrix[corr_matrix > above_threshold])
    inverse = pd.DataFrame(corr_matrix[corr_matrix < below_threshold])

    high_corr = pd.DataFrame()
    high_corr['high_combinations_1'] = high.index.get_level_values(0)
    high_corr['high_combinations_2'] = high.index.get_level_values(1)
    high_corr['values'] = high.values
    high_corr = high_corr[np.isfinite(high_corr['values'])]
    mask1 = high_corr['high_combinations_1'].isin(lst)
    mask2 = high_corr['high_combinations_2'].isin(lst)
    high_corr = high_corr[mask1]
    high_corr = high_corr[mask2]

    inverse_corr = pd.DataFrame()
    inverse_corr['inverse_combinations_1'] = inverse.index.get_level_values(0)
    inverse_corr['inverse_combinations_2'] = inverse.index.get_level_values(1)
    inverse_corr['values'] = inverse.values
    inverse_corr = inverse_corr[np.isfinite(inverse_corr['values'])]
    mask1 = inverse_corr['inverse_combinations_1'].isin(lst)
    mask2 = inverse_corr['inverse_combinations_2'].isin(lst)
    inverse_corr = inverse_corr[mask1]
    inverse_corr = inverse_corr[mask2]

    if export_to_csv:
        corr_matrix.to_csv(f"{export_path}_correlated_museums_{cm_timedelta}_.csv", index=False)

    return m, high_corr, inverse_corr


def plot_national_museum_entries(db_connection, export_to_csv, export_path, plotname):

    """
    Plot National Museum Entries
    """
    
    data = get_national_museums(db_connection, export_to_csv, export_path)
    data = data[data['visit_month'].isin(['June', 'July', 'August', 'September'])]
    data = data.sort_values(['visit_month'], ascending=True)

    trace1 = Bar(
        x=data.museum_id,
        y=data.total_visitors,
        name='FirenzeCard',
        marker=dict(color='#CC171D'),
    )

    fig = go.Figure(data=go.Data([trace1]))
    plot_url = py.iplot(fig, plotname, sharing='private')

    return data, plot_url


def plot_geomap_timeseries(df, df_timeseries, geomap_timedelta, date_to_plot, plotname, mapbox_access_token, min_timedelta,
                           max_timedelta):

    """
    Plot geographical mapbox of timeseries data, for a given day
    """

    df = df[df['date'] == date_to_plot]
    df = df[['museum_id', 'latitude', 'longitude', 'short_name']].drop_duplicates()
    df2 = pd.merge(df, df_timeseries, on=['museum_id'], how='inner')
    df2 = df2[[geomap_timedelta, "total_entries", 'latitude', 'longitude', 'short_name']]

    df2['short_name'][df2.total_entries == 0] = float('nan')
    df2['latitude'][df2.total_entries == 0] = float('nan')
    df2['longitude'][df2.total_entries == 0] = float('nan')
    df2.set_index('short_name', inplace=True)
    df2['short_name'] = df2.index
    df2['name_entries'] = df2['short_name'].astype(str) + ': ' + df2['total_entries'].astype(str)
    df2 = df2[df2.hour >= min_timedelta]
    df2 = df2[df2.hour <= max_timedelta]

    data = []
    for hour in list(df2[geomap_timedelta].unique()):
        trace = dict(
            lat=df2[df2[geomap_timedelta] == hour]['latitude'],
            lon=df2[df2[geomap_timedelta] == hour]['longitude'],
            name=hour,
            mode='marker',
            marker=dict(size=7),
            text=df2[df2[geomap_timedelta] == hour]['name_entries'],
            type='scattermapbox',
            hoverinfo='text'
        )

        data.append(trace)

    museums = list([
        dict(
            args=[{
                'mapbox.center.lat': 43.768,
                'mapbox.center.lon': 11.262,
                'mapbox.zoom': 12,
                'annotations[0].text': 'Museums in Florence'
            }],
            label='Florence',
            method='relayout'
        )
    ])

    m = df2[['latitude', 'longitude']].drop_duplicates()
    for museum, row in m.iterrows():
        desc = []
        for col in m.columns:
            if col not in ['latitude', 'longitude']:
                if str(row[col]) not in ['None', 'nan', '']:
                    desc.append(col + ': ' + str(row[col]).strip("'"))
        desc.insert(0, museum)
        museums.append(
            dict(
                args=[{
                    'mapbox.center.lat': row['latitude'],
                    'mapbox.center.lon': float(str(row['longitude']).strip("'")),
                    'mapbox.zoom': 14,
                }],
                label=museum,
                method='relayout'
            )
        )

    updatemenus = list([
        dict(
            buttons=list([
                dict(
                    args=['mapbox.style', 'light'],
                    label='Map',
                    method='relayout'
                ),
                dict(
                    args=['mapbox.style', 'satellite-streets'],
                    label='Satellite',
                    method='relayout'
                )
            ]),
            direction='up',
            x=0.75,
            xanchor='left',
            y=0.05,
            yanchor='bottom',
            bgcolor='#ffffff',
            bordercolor='#000000',
            font=dict(size=11)
        ),
    ])

    layout = Layout(
        showlegend=True,
        autosize=False,
        hovermode='closest',
        mapbox=dict(
            accesstoken=mapbox_access_token,
            bearing=0,
            center=dict(
                lat=43.768,
                lon=11.262
            ),
            pitch=0,
            zoom=12
        ),
    )

    layout['updatemenus'] = updatemenus
    fig = dict(data=data, layout=layout)
    plot_url = py.iplot(fig, plotname, sharing='private', auto_open=False)

    return df2, plot_url


def plot_fc_and_statemuseum_monthly_timeseries(df_date, db_connection, plotname):

    """
    Plot Firenzecard and State Museum monthly aggregate timeseries.
    """

    # Histogram of Monthly total museum entry data for Firenze Card and National State Museums
    statemuseum_data = get_national_museums(db_connection, export_to_csv=True, export_path='../src/output/')
    statemuseum_data = statemuseum_data[(statemuseum_data['visit_month'] == 'June') |
                                        (statemuseum_data['visit_month'] == 'July') |
                                        (statemuseum_data['visit_month'] == 'August') |
                                        (statemuseum_data['visit_month'] == 'September')]
    states_months = statemuseum_data.groupby('visit_month', as_index=False)['total_visitors'].sum().to_frame()

    # todo clean this up
    fc_june = df_date['All Museums'][(df_date['All Museums']['date'] > '2016-06-01') &
                                     (df_date['All Museums']['date'] < '2016-06-31')]['total_entries'].sum()
    fc_july = df_date['All Museums'][(df_date['All Museums']['date'] > '2016-07-01') &
                                     (df_date['All Museums']['date'] < '2016-07-31')]['total_entries'].sum()
    fc_august = df_date['All Museums'][(df_date['All Museums']['date'] > '2016-08-01') &
                                       (df_date['All Museums']['date'] < '2016-08-31')]['total_entries'].sum()
    fc_september = df_date['All Museums'][(df_date['All Museums']['date'] > '2016-09-01') &
                                          (df_date['All Museums']['date'] < '2016-09-30')]['total_entries'].sum()

    df2 = pd.DataFrame()
    df2['month'] = ['June', 'July', 'August', 'September']
    df2['firenzecard_entries'] = [fc_june, fc_july, fc_august, fc_september]

    df2['state_entries'] = [states_months[states_months['visit_month'] == 'June']['total_visitors'],
                            states_months[states_months['visit_month'] == 'July']['total_visitors'],
                            states_months[states_months['visit_month'] == 'August']['total_visitors'],
                            states_months[states_months['visit_month'] == 'September']['total_visitors']]

    trace1 = Bar(
        x=df2.month,
        y=df2.firenzecard_entries,
        name='FirenzeCard'
    )

    trace2 = Bar(
        x=df2.month,
        y=df2.state_entries,
        name='State Museums'
    )

    fig = go.Figure(data=go.Data([trace1, trace2]))
    plot_url = py.iplot(fig, plotname, sharing='private')

    return df2, plot_url


def get_timelines_of_usage(df_hour, df_date, df_dow, hour_min, hour_max):

    """
    Get timelines of usage of Firenzecard data.
    """

    df_hour = df_hour[(df_hour['hour'] >= hour_min) & (df_hour['hour'] <= hour_max)]

    # How many users are there per day / hour / day-of-week on average across all museums, over the entire summer?
    df2_date = df_date.groupby('date', as_index=False)['total_entries'].mean()
    df2_hour = df_hour.groupby('hour', as_index=False)['total_entries'].mean()
    df2_dow = df_dow.groupby('day_of_week', as_index=False)['total_entries'].mean()

    return df2_hour, df2_dow, df2_date


def plot_museum_aggregate_entries(df, plotname):

    """
    Plot total museum entries over entries summer 2016, for each museum.
    """

    df2 = df.groupby('short_name', as_index=True).sum()['total_people'].to_frame()
    df2.sort_values('total_people', inplace=True, ascending=True)

    trace = Bar(
        x=df2.index,
        y=df2['total_people'],
        marker=dict(color='#CC171D'),
    )

    fig = go.Figure(data=go.Data([trace]))
    plot_url = py.iplot(fig, plotname, sharing='private', auto_open=False)

    return df2, plot_url


def plot_museums_visited_per_card(df, plotname):

    """
    Plot frequency plot of number of unique museums visited per card
    """

    df2 = df[['user_id', 'entry_is_adult', 'museum_id', 'date']]
    df2 = df2.groupby(['user_id'], as_index=True).museum_id.nunique().rename('total_museums_per_card').to_frame()

    trace1 = go.Histogram(x=df2.total_museums_per_card, xbins=dict(start=np.min(df2.total_museums_per_card) - 0.25,
                                                                   size=0.5,
                                                                   end=np.max(df2.total_museums_per_card)),
                          marker=dict(color='#CC171D'))

    layout = go.Layout(
        title="Total number of museums visited per card",
        legend=dict(
            traceorder='normal',
            font=dict(
                family='sans-serif',
                size=12,
                color='#000'
            ),
            bgcolor='#E2E2E2',
            bordercolor='#FFFFFF',
            borderwidth=2
        )
    )

    fig = go.Figure(data=go.Data([trace1]), layout=layout)
    plot_url1 = py.iplot(fig, plotname, sharing='private', auto_open=False)

    return df2, plot_url1


def plot_day_of_activation(df, plotname):

    """
    Plots Aggregate of Day of Activation.
    """

    # todo sort order in logical day order
    dotw = {0: 'Monday',
            1: 'Tuesday',
            2: 'Wednesday',
            3: 'Thursday',
            4: 'Friday',
            5: 'Saturday',
            6: 'Sunday'}
    df2 = df[df['adults_first_use'] == 1][['user_id', 'day_of_week']]
    df2 = df2.groupby('user_id', as_index=False).mean()['day_of_week'].map(dotw).to_frame()
    df2 = df2['day_of_week'].value_counts().to_frame()

    # todo fix the X axis labeling so it's not hardcoded!
    trace = go.Bar(x=['Tuesday', 'Wednesday', 'Friday', 'Thursday', 'Satuday', 'Sunday', 'Monday'],
                   y=df2.day_of_week,
                   marker=dict(color='#CC171D'))

    layout = go.Layout(
        title="Day of Firenze Card Activation",
        xaxis=dict(
            title='Day of the Week',
            nticks=7,
            ticks='outside',
        ),
        yaxis=dict(
            title='Number of Cards Activated',
            ticks='outside',
        )
    )
    fig = go.Figure(data=go.Data([trace]), layout=layout)
    plot_url = py.iplot(fig, plotname, sharing='private', auto_open=False)

    return df2, plot_url

